from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import (
    AdmissionOfferingModel,
    AdmissionPassingScoreModel,
)
from andromeda.infrastructure.repositories.admissions import (
    SqlAlchemyAdmissionRepository,
)
from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.modules.admissions.contracts.offering_revisions import (
    admission_offering_domain_rule_id,
    admission_offering_revision_hash,
)
from andromeda.modules.admissions.contracts.public import (
    AdmissionCompetitionType,
    ExamRequirement,
    PassingScore,
    PassingScoreStatus,
    PassingScoreType,
)


def test_admission_projection_round_trips_through_repository_and_preserves_fk(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()

    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'admissions.db').as_posix()}")
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)

    with Session(engine) as session:
        admissions = SqlAlchemyAdmissionRepository(session).get_for_program("program:09.03.01-02")
        offering_ids = [offering.id for offering in admissions.offerings]
        persisted_program_ids = session.scalars(
            select(AdmissionOfferingModel.program_id).where(AdmissionOfferingModel.id.in_(offering_ids))
        ).all()

    assert len(admissions.offerings) == 10
    assert set(persisted_program_ids) == {"program:bmstu:09.03.01-02"}
    assert all(offering.program_id == "program:bmstu:09.03.01-02" for offering in admissions.offerings)
    assert any(offering.tuition for offering in admissions.offerings)
    assert any(offering.passing_scores for offering in admissions.offerings)
    foreign_keys = inspect(engine).get_foreign_keys("admission_offerings")
    assert any(foreign_key["referred_table"] == "educational_programs" and foreign_key["constrained_columns"] == ["program_id"] for foreign_key in foreign_keys)


def test_batch_admission_reader_matches_single_program_contract(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()

    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'admissions-batch.db').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
        with Session(engine) as session:
            repository = SqlAlchemyAdmissionRepository(session)
            batch = repository.get_for_programs(("program:09.03.01-02", "program:09.03.01-12"))
            single = repository.get_for_program("program:09.03.01-02")

        assert tuple(item.program_id for item in batch) == (
            "program:bmstu:09.03.01-02",
            "program:bmstu:09.03.01-12",
        )
        assert batch[0] == single
        assert len(batch[1].offerings) == 10
    finally:
        engine.dispose()


def test_route_aware_passing_scores_round_trip_and_stale_children_are_removed(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()

    target_program = next(item for item in canonical.admissions if item.program_id == "program:bmstu:09.03.01-02")
    target_offering = next(item for item in target_program.offerings if item.admission_year == 2026 and item.funding_type.value == "budget")
    source = target_offering.provenance[0]
    route_scores = (
        PassingScore(
            score_type=PassingScoreType.BUDGET,
            competition_type=AdmissionCompetitionType.GENERAL,
            score=Decimal(220),
            provenance=source,
        ),
        PassingScore(
            score_type=PassingScoreType.BUDGET,
            competition_type=AdmissionCompetitionType.TARGETED,
            score=Decimal(195),
            provenance=source,
        ),
        PassingScore(
            score_type=PassingScoreType.BUDGET,
            competition_type=AdmissionCompetitionType.SEPARATE_QUOTA,
            status=PassingScoreStatus.BVI,
            score=None,
            provenance=source,
        ),
    )
    updated_offering = target_offering.model_copy(update={"passing_scores": route_scores})
    updated_program = target_program.model_copy(update={"offerings": (updated_offering, *[item for item in target_program.offerings if item.id != target_offering.id])})
    updated_canonical = canonical.model_copy(
        update={
            "admissions": (updated_program, *[item for item in canonical.admissions if item.program_id != target_program.program_id]),
        }
    )

    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'route-aware-admissions.db').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        ingestion = SqlAlchemyIngestionRepository(engine)
        ingestion.ingest(raw, updated_canonical)
        ingestion.ingest(raw, updated_canonical)

        with Session(engine) as session:
            rows = session.scalars(
                select(AdmissionPassingScoreModel).where(AdmissionPassingScoreModel.offering_id == target_offering.id)
            ).all()
            loaded = SqlAlchemyAdmissionRepository(session).get_for_program("program:09.03.01-02")

        assert len(rows) == 3
        assert {(row.competition_type, row.status, row.score) for row in rows} == {
            ("general", "numeric", Decimal("220.00")),
            ("targeted", "numeric", Decimal("195.00")),
            ("separate_quota", "bvi", None),
        }
        loaded_offering = next(item for item in loaded.offerings if item.id == target_offering.id)
        assert {(item.competition_type.value, item.status.value, item.score) for item in loaded_offering.passing_scores} == {
            ("general", "numeric", Decimal("220.00")),
            ("targeted", "numeric", Decimal("195.00")),
            ("separate_quota", "bvi", None),
        }

        replacement = updated_offering.model_copy(update={"passing_scores": (route_scores[0],)})
        replaced_program = target_program.model_copy(update={"offerings": (replacement, *[item for item in target_program.offerings if item.id != target_offering.id])})
        replaced_canonical = updated_canonical.model_copy(
            update={
                "admissions": (replaced_program, *[item for item in updated_canonical.admissions if item.program_id != target_program.program_id]),
            }
        )
        ingestion.ingest(raw, replaced_canonical)
        with Session(engine) as session:
            remaining = session.scalars(
                select(AdmissionPassingScoreModel).where(AdmissionPassingScoreModel.offering_id == target_offering.id)
            ).all()
        assert len(remaining) == 1
        assert remaining[0].competition_type == "general"
    finally:
        engine.dispose()


def test_campus_and_choice_group_metadata_round_trip_without_collapsing_offerings(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()

    target = next(item for item in canonical.admissions if item.program_id == "program:bmstu:09.03.01-02")
    existing = next(item for item in target.offerings if item.admission_year == 2026 and item.funding_type.value == "budget")
    source = existing.provenance[0]
    group_id = "exam-choice:ege-third"
    grouped_exams = (
        ExamRequirement(
            subject="Физика",
            source_name="Физика",
            is_choice=True,
            choice_group_id=group_id,
            choice_group_min=1,
            choice_group_max=1,
            provenance=source,
        ),
        ExamRequirement(
            subject="Информатика",
            source_name="Информатика",
            is_choice=True,
            choice_group_id=group_id,
            choice_group_min=1,
            choice_group_max=1,
            provenance=source,
        ),
    )
    campus_offering = existing.model_copy(
        update={
            "id": f"{existing.id}:campus:bmstu-kaluga",
            "campus_id": "campus:bmstu-kaluga",
            "exams": grouped_exams,
        }
    )
    changed_program = target.model_copy(update={"offerings": (*target.offerings, campus_offering)})
    changed_canonical = canonical.model_copy(
        update={"admissions": (changed_program, *[item for item in canonical.admissions if item.program_id != target.program_id])}
    )

    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'campus-choice-admissions.db').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        SqlAlchemyIngestionRepository(engine).ingest(raw, changed_canonical)
        with Session(engine) as session:
            loaded = SqlAlchemyAdmissionRepository(session).get_for_program("program:09.03.01-02")

        same_scope = [
            item
            for item in loaded.offerings
            if item.admission_year == 2026
            and item.funding_type is not None
            and item.funding_type.value == "budget"
            and item.study_form is not None
            and item.study_form.value == "full_time"
        ]
        assert {item.campus_id for item in same_scope} == {None, "campus:bmstu-kaluga"}
        restored = next(item for item in same_scope if item.campus_id == "campus:bmstu-kaluga")
        assert {exam.choice_group_id for exam in restored.exams} == {group_id}
        assert {(exam.choice_group_min, exam.choice_group_max) for exam in restored.exams} == {(1, 1)}
    finally:
        engine.dispose()


def test_offering_owner_revisions_are_append_only_exact_and_idempotent(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(
            fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
        )
    finally:
        adapter.close()

    program = next(item for item in canonical.admissions if item.program_id == "program:bmstu:09.03.01-02")
    offering = next(item for item in program.offerings if item.admission_year == 2026)
    domain_rule_id = admission_offering_domain_rule_id(offering.id)
    first_hash = admission_offering_revision_hash(offering)
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'admission-revisions.db').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        ingestion = SqlAlchemyIngestionRepository(engine)
        ingestion.ingest(raw, canonical)
        ingestion.ingest(raw, canonical)

        with Session(engine) as session:
            repository = SqlAlchemyAdmissionRepository(session)
            first = repository.get_offering_revision(domain_rule_id, 1, first_hash)
            assert first is not None
            assert first.offering == offering
            assert repository.get_offering_revision(domain_rule_id, 2, first_hash) is None

        original_exam = offering.exams[0]
        changed_minimum = (
            Decimal(80)
            if original_exam.minimum_score is None
            else Decimal(1)
            if original_exam.minimum_score >= Decimal(100)
            else original_exam.minimum_score + Decimal(1)
        )
        changed_exam = original_exam.model_copy(update={"minimum_score": changed_minimum})
        changed_offering = offering.model_copy(
            update={"exams": (changed_exam, *offering.exams[1:])}
        )
        changed_program = program.model_copy(
            update={
                "offerings": (
                    changed_offering,
                    *(item for item in program.offerings if item.id != offering.id),
                )
            }
        )
        changed_canonical = canonical.model_copy(
            update={
                "admissions": (
                    changed_program,
                    *(item for item in canonical.admissions if item.program_id != program.program_id),
                )
            }
        )
        second_hash = admission_offering_revision_hash(changed_offering)
        assert second_hash != first_hash
        ingestion.ingest(raw, changed_canonical)
        ingestion.ingest(raw, changed_canonical)

        with Session(engine) as session:
            repository = SqlAlchemyAdmissionRepository(session)
            first = repository.get_offering_revision(domain_rule_id, 1, first_hash)
            second = repository.get_offering_revision(domain_rule_id, 2, second_hash)
            assert first is not None and first.offering == offering
            assert second is not None and second.offering == changed_offering
            assert repository.get_offering_revision(domain_rule_id, 3, second_hash) is None
    finally:
        engine.dispose()
