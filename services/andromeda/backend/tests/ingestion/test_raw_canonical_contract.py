from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError

from andromeda.ingestion.contracts.raw import RawCampusPointRecord, RawSourceGap, RawSourceSnapshot, SourceLocator
from andromeda.ingestion.contracts.source import gap_severity_for_reason, source_gap_reference
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import GapSeverity, SourceAttribution


def test_raw_source_contract_rejects_extra_fields_and_preserves_provenance() -> None:
    body = b"fixture"
    snapshot = RawSourceSnapshot(
        source_kind="bmstu_common",
        requested_url="https://bmstu.ru/sveden/common/",
        final_url="https://bmstu.ru/sveden/common/",
        status_code=200,
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        content_sha256=sha256(body).hexdigest(),
        body=body,
    )
    assert snapshot.final_url == snapshot.requested_url

    with pytest.raises(ValidationError):
        RawSourceSnapshot.model_validate({**snapshot.model_dump(), "unexpected": True})


def test_public_provenance_is_field_scoped_and_gaps_have_safe_severity() -> None:
    attribution = SourceAttribution(
        kind=SourceKind.BMSTU_CURRICULUM_DOCUMENT,
        url="https://bmstu.ru/plan.pdf",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        content_sha256=sha256(b"fixture").hexdigest(),
        university_id="university:bmstu",
        run_id="ingest:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        field="curriculum",
        record_key="program:bmstu:09.03.01-02",
    )
    assert attribution.field == "curriculum"
    assert "body" not in attribution.model_dump()
    gap = source_gap_reference(
        RawSourceGap(
            id="source-gap:aaaaaaaaaaaaaaaaaaaaaaaa",
            entity_type="program",
            entity_key="program:bmstu:09.03.01-02",
            reason="passing_score_missing",
            source_url="https://bmstu.ru/admission",
            locator=SourceLocator(source_url="https://bmstu.ru/admission"),
        ),
        field="passing_score",
        record_key="program:bmstu:09.03.01-02",
    )
    assert gap.severity is GapSeverity.DEGRADABLE
    assert gap.can_continue is True


@pytest.mark.parametrize(
    ("reason", "severity"),
    (
        ("program_detail_parse_failed", GapSeverity.BLOCKING),
        ("direction_section_not_published", GapSeverity.DEGRADABLE),
        ("order_direction_not_in_catalog", GapSeverity.INFORMATIONAL),
        ("program education year is absent from official sources", GapSeverity.DEGRADABLE),
        ("competition_heading_unknown:page=7;section=4", GapSeverity.DEGRADABLE),
        ("admission-program-identity-unknown", GapSeverity.INFORMATIONAL),
        ("admission-program-identity-ambiguous", GapSeverity.DEGRADABLE),
        ("work-plan-program-identity-ambiguous", GapSeverity.DEGRADABLE),
        ("work-plan-document-produced-no-rows", GapSeverity.DEGRADABLE),
    ),
)
def test_source_gap_severity_policy_distinguishes_projection_blockers(reason: str, severity: GapSeverity) -> None:
    assert gap_severity_for_reason(reason) is severity


def test_locator_is_typed_and_explicitly_nullable() -> None:
    locator = SourceLocator(source_url="https://bmstu.ru/", page=None, row=2, field=None)
    assert locator.page is None
    assert locator.row == 2


def test_raw_campus_point_contract_rejects_partial_coordinates() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        RawCampusPointRecord(
            external_key="main-campus",
            point_type="building",
            name="Главный корпус",
            latitude=Decimal("55.7666"),
            longitude=None,
            university_ids=("university:bmstu",),
            source_kind="bmstu_campus_points",
            source_url="https://bmstu.ru/campus/points",
            locator=SourceLocator(source_url="https://bmstu.ru/campus/points", row=1),
        )
