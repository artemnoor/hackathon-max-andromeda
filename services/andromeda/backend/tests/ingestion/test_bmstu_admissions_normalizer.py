from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from andromeda.ingestion.contracts.raw import (
    RawAdmissionPassingScore,
    RawAdmissionRecord,
    RawProgramRecord,
    RawSourceSnapshot,
    SourceLocator,
)
from andromeda.ingestion.contracts.source import CapturedSources
from andromeda.ingestion.universities.bmstu.adapter import _canonicalize_admission_records
from andromeda.ingestion.universities.bmstu.normalizers.admissions import normalize_admissions
from andromeda.modules.programs.domain.entities import Program


def _program(code: str) -> Program:
    return Program(
        id=f"program:{code}",
        direction_id="direction:09.03.01",
        code=code,
        name=f"Profile {code}",
        education_year=2026,
        study_plan_url="https://bmstu.ru/plans/example.pdf",
        source_url="https://bmstu.ru/program/example",
    )


def _raw_program(code: str) -> RawProgramRecord:
    return RawProgramRecord(
        code=code,
        name=f"Profile {code}",
        direction_code="09.03.01",
        education_level="бакалавриат",
        education_year=2026,
        study_plan_url="https://bmstu.ru/plans/example.pdf",
        source_url="https://bmstu.ru/program/example",
        locator=SourceLocator(source_url="https://bmstu.ru/program/example"),
    )


def _snapshot(url: str, digest: str) -> RawSourceSnapshot:
    return RawSourceSnapshot(
        source_kind="bmstu_major_detail" if "detail" in url else "bmstu_admission_orders_document",
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="application/json",
        captured_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        content_sha256=digest * 64,
        body=url.encode("utf-8"),
    )


def _record(
    *,
    url: str,
    year: int,
    score: Decimal | None,
    route: str = "general",
    status: str = "numeric",
) -> RawAdmissionRecord:
    passing = RawAdmissionPassingScore(
        score_type="budget",
        competition_type=route,
        status=status,
        score=score,
    )
    return RawAdmissionRecord(
        id=f"record:{url}:{year}:{route}:{status}:{score}",
        program_code="09.03.01",
        admission_year=year,
        funding_type="budget",
        scope="direction",
        passing_scores=(passing,),
        source_kind="bmstu_major_detail" if "detail" in url else "bmstu_admission_orders_document",
        source_url=url,
        locator=SourceLocator(source_url=url, field=f"route={route};status={status}"),
    )


def test_normalizer_keeps_routes_and_selects_order_minimum_deterministically() -> None:
    detail_url = "https://bmstu.ru/detail/09.03.01"
    order_url = "https://priem.bmstu.ru/lists/orders.pdf"
    snapshots = CapturedSources(
        snapshots=(
            _snapshot(detail_url, "a"),
            _snapshot(order_url, "b"),
        )
    )
    records = (
        _record(url=detail_url, year=2026, score=Decimal("230")),
        _record(url=order_url, year=2026, score=Decimal("225")),
        _record(url=order_url, year=2026, score=Decimal("220")),
        _record(url=order_url, year=2026, score=Decimal("195"), route="targeted"),
        _record(url=order_url, year=2026, score=None, route="separate_quota", status="bvi"),
        _record(url=detail_url, year=2025, score=Decimal("210")),
    )
    programs = (_program("09.03.01-02"), _program("09.03.01-12"))

    forward = normalize_admissions(records, programs=programs, snapshots=snapshots.snapshots)
    reverse = normalize_admissions(tuple(reversed(records)), programs=programs, snapshots=snapshots.snapshots)

    assert forward == reverse
    offering = next(item for item in forward[0].offerings if item.admission_year == 2026)
    assert {(item.competition_type.value, item.status.value, item.score) for item in offering.passing_scores} == {
        ("general", "numeric", Decimal("220")),
        ("targeted", "numeric", Decimal("195")),
        ("separate_quota", "bvi", None),
    }
    general = next(item for item in offering.passing_scores if item.competition_type.value == "general")
    assert general.provenance.source_kind == "bmstu_admission_orders_document"
    assert any(item.admission_year == 2025 for item in forward[0].offerings)


def test_normalizer_fans_direction_fact_out_to_all_profiles() -> None:
    url = "https://priem.bmstu.ru/lists/orders.pdf"
    source = _snapshot(url, "c")
    result = normalize_admissions(
        (_record(url=url, year=2026, score=Decimal("195"), route="targeted"),),
        programs=(_program("09.03.01-02"), _program("09.03.01-12")),
        snapshots=(source,),
    )

    assert {item.program_id for item in result} == {"program:09.03.01-02", "program:09.03.01-12"}
    assert all(item.offerings[0].passing_scores[0].competition_type.value == "targeted" for item in result)


def test_adapter_quarantines_unknown_admission_identity_without_fabricating_projection() -> None:
    unknown = _record(
        url="https://bmstu.ru/detail/01.03.02",
        year=2026,
        score=Decimal("210"),
    ).model_copy(update={"program_code": "01.03.02"})
    known = _record(
        url="https://bmstu.ru/detail/09.03.01",
        year=2026,
        score=Decimal("220"),
    )

    records, gaps = _canonicalize_admission_records(
        (unknown, known),
        (_raw_program("09.03.01-02"),),
    )

    assert tuple(record.program_code for record in records) == ("09.03.01",)
    assert len(gaps) == 1
    assert gaps[0].reason == "admission-program-identity-unknown"
    assert gaps[0].entity_type == "admission"
