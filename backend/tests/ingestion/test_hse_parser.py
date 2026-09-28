from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

import fitz

from andromeda.ingestion.contracts.constraints import http_url
from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.contracts.source import CapturedSources, source_fetch_gap
from andromeda.ingestion.universities.hse.adapter import HseUniversityAdapter
from andromeda.ingestion.universities.hse.identity import canonicalize_program_records
from andromeda.ingestion.universities.hse.parser.admissions import parse_enrollment_document
from andromeda.ingestion.universities.hse.parser.catalog import discover_program_links, parse_program_detail
from andromeda.ingestion.universities.hse.parser.curriculum import parse_work_plan
from andromeda.modules.disciplines.services.classifier import RuleBasedDisciplineClassifier


def _snapshot(kind: str, url: str, body: bytes) -> RawSourceSnapshot:
    now = datetime.now(timezone.utc)
    return RawSourceSnapshot(source_kind=kind, requested_url=http_url(url), final_url=http_url(url), status_code=200, content_type="application/pdf" if body.startswith(b"%PDF") else "text/html", captured_at=now, content_sha256=sha256(body).hexdigest(), body=body)


def test_hse_catalog_normalizes_admission_link_without_hardcoded_programs() -> None:
    body = b"""
    <a href="https://www.hse.ru/ba/ami/">AMI</a>
    <a href="https://www.hse.ru/ba/neuroscience/admission/">Neuro</a>
    <a href="https://example.test/ba/nope/">External</a>
    """
    assert discover_program_links(body, "https://admissions.hse.ru/undergraduate-apply/programmes_list") == (
        "https://www.hse.ru/ba/ami/",
        "https://www.hse.ru/ba/neuroscience/",
    )


def test_hse_program_identity_is_stable_and_keeps_source_url() -> None:
    from andromeda.ingestion.contracts.raw import RawDirectionRecord, RawProgramRecord, SourceLocator

    direction = RawDirectionRecord(code="01.03.02", name="Прикладная математика и информатика", education_level="бакалавриат", locator=SourceLocator(source_url=http_url("https://www.hse.ru/ba/ami/")))
    values = tuple(
        RawProgramRecord(code="pending", name=name, direction_code=direction.code, education_level="бакалавриат", education_year=2026, study_plan_url=http_url(url + "learn_plans/"), source_url=http_url(url), locator=direction.locator, source_code=url)
        for name, url in (("Прикладная математика и информатика", "https://www.hse.ru/ba/ami/"), ("Компьютерные науки и анализ данных", "https://www.hse.ru/ba/data/"))
    )
    first = canonicalize_program_records(values)
    second = canonicalize_program_records(values)
    assert tuple(value.code for value in first) == tuple(value.code for value in second)
    assert all(value.code.startswith("01.03.02-") for value in first)
    assert all(value.source_code.startswith("https://www.hse.ru/ba/") for value in first)


def test_hse_missing_education_year_is_unknown_not_current_year() -> None:
    snapshot = _snapshot("hse_program_detail", "https://www.hse.ru/ba/ami/", b"<h1>Applied Mathematics</h1><p>01.03.02</p>")
    assert parse_program_detail(snapshot).education_year is None


def test_hse_enrollment_parser_preserves_bvi_status(monkeypatch) -> None:
    import andromeda.ingestion.universities.hse.parser.admissions as admissions

    monkeypatch.setattr(
        admissions,
        "extract_pdf_text",
        lambda _: """Очная форма обучения\nСведения о лицах, зачисленных без вступительных испытаний\n974823 01.03.02 Прикладная математика и информатика Победитель олимпиады\n""",
    )
    observations = parse_enrollment_document(_snapshot("hse_enrollment_document", "https://ba.hse.ru/mirror/pubs/share/1", b"%PDF synthetic"))
    assert observations[0].status == "bvi"
    assert observations[0].score is None
    assert observations[0].competition_type == "bvi"


def test_hse_adapter_emits_canonical_snapshot_from_discovered_sources() -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 60), "Direction 01.03.02 Applied Mathematics\nProgram Applied Mathematics\n1 Algebra O 3,00 114 36")
    pdf = document.tobytes()
    snapshots = CapturedSources(
        (
            _snapshot("hse_common", "https://www.hse.ru/contacts/", "<div>109028, г. Москва, Покровский бульвар, д. 11</div>".encode()),
            _snapshot("hse_program_detail", "https://www.hse.ru/ba/ami/", "<h1>Applied Mathematics</h1><p>01.03.02 · 2026</p>".encode()),
            _snapshot("hse_admission_rules", "https://ba.hse.ru/minkrit", "<table><tr><th>h</th></tr><tr><td>Direction 01.03.02 Applied Mathematics</td></tr><tr><td>1</td><td>Applied Mathematics</td><td>mathematics</td><td>75</td></tr></table>".encode()),
            _snapshot("hse_curriculum_document", "https://www.hse.ru/dbs/education/sp_UnitedWorkPlan_test.pdf", pdf),
        ),
        source_gaps=(source_fetch_gap("hse_tuition", "https://ba.hse.ru/price", "source_unavailable"),),
    )
    adapter = HseUniversityAdapter()
    try:
        raw, canonical = adapter.parse(snapshots)
    finally:
        adapter.close()
    assert len(raw.programs) == 1
    assert canonical.university.id == "university:hse"
    assert canonical.programs[0].code.startswith("01.03.02-")
    assert canonical.curricula[0].items[0].hours == 114
    assert canonical.curricula[0].items[0].semester is None
    assert raw.source_gaps[0].reason == "source_unavailable"
    assert raw.diagnostics[0].code == "source_unavailable"
    assert sum((weight.weight for weight in canonical.disciplines[0].area_weights), start=0) == 1


def test_hse_work_plan_parser_accepts_official_english_course_types() -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 60), "Field of study 01.03.02 Applied Mathematics\nEducational Programme Data Science\n1 Algebra C 3,00 114 36\n2 Statistics E 4,00 152 48")
    snapshot = _snapshot(
        "hse_curriculum_document",
        "https://www.hse.ru/dbs/education/sp_EngUnitedWorkPlan_test.pdf",
        document.tobytes(),
    )

    observations = parse_work_plan(snapshot)

    assert [(item.discipline, item.credits, item.hours) for item in observations] == [
        ("Algebra", "3.00", 114),
        ("Statistics", "4.00", 152),
    ]
    assert observations[0].direction_code_candidates == ("01.03.02",)


def test_hse_work_plan_keeps_all_direction_codes_from_official_header() -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 60), "Field of study 38.03.01 Economics, 38.03.02 Management\nEducational Programme International Business\n1 Finance C 3,00 114 36")
    snapshot = _snapshot(
        "hse_curriculum_document",
        "https://www.hse.ru/dbs/education/sp_EngUnitedWorkPlan_multi.pdf",
        document.tobytes(),
    )

    observations = parse_work_plan(snapshot)

    assert observations[0].direction_code_candidates == ("38.03.01", "38.03.02")


def test_hse_adapter_uses_curriculum_index_owner_for_shared_direction_codes() -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 60), "Direction 01.03.02 Applied Mathematics\nEducational Programme Unknown\n1 Algebra O 3,00 114 36")
    pdf = document.tobytes()
    plan_url = "https://www.hse.ru/dbs/education/sp_UnitedWorkPlan_1_2.pdf"
    snapshots = CapturedSources(
        (
            _snapshot("hse_common", "https://www.hse.ru/contacts/", "<div>109028, г. Москва, Покровский бульвар, д. 11</div>".encode()),
            _snapshot("hse_program_detail", "https://www.hse.ru/ba/first/", "<h1>Programme A</h1><p>01.03.02 · 2026</p>".encode()),
            _snapshot("hse_program_detail", "https://www.hse.ru/ba/second/", "<h1>Programme B</h1><p>01.03.02 · 2026</p>".encode()),
            _snapshot("hse_curriculum_index", "https://www.hse.ru/ba/first/learn_plans/", f'<a href="{plan_url}">plan</a>'.encode()),
            _snapshot("hse_curriculum_index", "https://www.hse.ru/ba/second/learn_plans/", f'<a href="{plan_url}">shared plan</a>'.encode()),
            _snapshot("hse_curriculum_document", plan_url, pdf),
        )
    )
    adapter = HseUniversityAdapter()
    try:
        raw, canonical = adapter.parse(snapshots)
    finally:
        adapter.close()

    first_program = next(program for program in canonical.programs if program.source_url.path == "/ba/first/")
    second_program = next(program for program in canonical.programs if program.source_url.path == "/ba/second/")
    assert {str(curriculum.program_id) for curriculum in canonical.curricula} == {str(first_program.id), str(second_program.id)}
    assert not any(gap.reason == "work-plan-program-identity-ambiguous" for gap in raw.source_gaps)


def test_hse_classifier_returns_explicit_deterministic_vector() -> None:
    classifier = RuleBasedDisciplineClassifier()
    weights = classifier.classify("Математический анализ")
    assert sum((item.weight for item in weights), start=0) == 1
