from __future__ import annotations

from datetime import datetime, timezone

from andromeda.modules.admissions.contracts.public import AdmissionOffering, AdmissionProvenance, AdmissionScope
from andromeda.modules.admissions.domain.identity import offering_identity


def test_offering_identity_is_storage_independent() -> None:
    source = AdmissionProvenance(
        source_kind="fixture",
        source_url="https://example.test/admission",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        content_sha256="b" * 64,
    )
    offering = AdmissionOffering(
        id="admission-offering:program:09.03.01-02:2026:unknown:unknown:direction",
        program_id="program:09.03.01-02",
        admission_year=2026,
        scope=AdmissionScope.DIRECTION,
        provenance=(source,),
    )
    assert offering_identity(offering) == (
        "program:09.03.01-02",
        2026,
        None,
        None,
        AdmissionScope.DIRECTION,
    )
