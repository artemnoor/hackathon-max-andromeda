from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    EvidenceLocator,
    EvidenceRef,
    KnowledgeSourceKind,
    SourceAllowedRoute,
    SourceIdentity,
    SourceJurisdiction,
    SourceReliabilityTier,
)
from andromeda.modules.knowledge.domain.sources import (
    is_allowed_source_url,
    observation_id_from_idempotency_key,
    observation_idempotency_key,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _identity() -> SourceIdentity:
    return SourceIdentity(
        source_id="source:ministry-admission",
        issuer_id="issuer:minobrnauki",
        jurisdiction=SourceJurisdiction.FEDERAL,
        identity_key="admission-minimum-scores",
        display_name="Minobrnauki admission documents",
        created_at=NOW,
    )


def _revision(**updates: object) -> ApprovedSourceRegistryRevision:
    values: dict[str, object] = {
        "source_id": _identity().source_id,
        "revision": 1,
        "source_kind": KnowledgeSourceKind.NORMATIVE_DOCUMENT,
        "reliability_tier": SourceReliabilityTier.PRIMARY_NORMATIVE,
        "adapter_id": "ministry_documents",
        "adapter_version": "v1",
        "start_url": "https://official.example/admission/index",
        "allowlist": (SourceAllowedRoute(host="official.example", path_prefix="/admission"),),
        "poll_interval_seconds": 86_400,
        "freshness_budget_seconds": 604_800,
        "enabled": True,
        "approved_by_account_id": "account:" + "a" * 32,
        "approved_at": NOW,
        "approval_reason": "Approved pilot source",
        "recorded_at": NOW,
    }
    values.update(updates)
    return ApprovedSourceRegistryRevision.model_validate(values)


def test_source_identity_requires_timezone_aware_created_at() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        SourceIdentity(
            source_id="source:ministry-admission",
            issuer_id="issuer:minobrnauki",
            jurisdiction=SourceJurisdiction.FEDERAL,
            identity_key="admission-minimum-scores",
            display_name="Minobrnauki admission documents",
            created_at=datetime.fromisoformat("2026-09-25T00:00:00"),
        )


def test_registry_start_url_must_fit_versioned_https_allowlist() -> None:
    assert _revision().start_url.host == "official.example"
    with pytest.raises(ValidationError, match="match an explicit allowlist route"):
        _revision(start_url="https://official.example/other/index")
    with pytest.raises(ValidationError, match="HTTPS"):
        _revision(start_url="http://official.example/admission/index")
    with pytest.raises(ValidationError, match="HTTPS"):
        _revision(start_url="https://official.example:8443/admission/index")


@pytest.mark.parametrize(
    "path_prefix",
    ["/admission/../private", "/admission/%2e%2e/private", "/admission?mode=all", "relative"],
)
def test_allowlist_path_rejects_query_and_traversal(path_prefix: str) -> None:
    with pytest.raises(ValidationError):
        SourceAllowedRoute(host="official.example", path_prefix=path_prefix)


def test_source_allowlist_requires_exact_host_and_path_boundary() -> None:
    assert is_allowed_source_url(
        "https://official.example/admission/rules.pdf",
        host="official.example",
        path_prefix="/admission",
    )
    assert not is_allowed_source_url(
        "https://official.example.evil.test/admission/rules.pdf",
        host="official.example",
        path_prefix="/admission",
    )
    assert not is_allowed_source_url(
        "https://official.example/admission-old/rules.pdf",
        host="official.example",
        path_prefix="/admission",
    )
    assert not is_allowed_source_url(
        "https://official.example/admission/%2e%2e/private.pdf",
        host="official.example",
        path_prefix="/admission",
    )
    assert not is_allowed_source_url(
        "https://official.example/admission/rules.pdf?token=secret",
        host="official.example",
        path_prefix="/admission",
    )


def test_duplicate_registry_routes_and_unapproved_metadata_are_rejected() -> None:
    route = SourceAllowedRoute(host="official.example", path_prefix="/admission")
    with pytest.raises(ValidationError, match="routes must be unique"):
        _revision(allowlist=(route, route))
    with pytest.raises(ValidationError):
        _revision(approved_by_account_id="account:bad")


def test_observation_identity_is_repeatable_per_source_run_url_and_content() -> None:
    key = observation_idempotency_key(
        source_id="source:ministry-admission",
        registry_revision=1,
        ingest_run_id="ingest:" + "b" * 32,
        requested_url="https://official.example/admission/rules.pdf",
        snapshot_sha256="c" * 64,
    )
    assert len(key) == 64
    assert observation_id_from_idempotency_key(key) == "source-observation:" + key[:32]
    with pytest.raises(ValueError, match="query"):
        observation_idempotency_key(
            source_id="source:ministry-admission",
            registry_revision=1,
            ingest_run_id="ingest:" + "b" * 32,
            requested_url="https://official.example/admission/rules.pdf?token=secret",
            snapshot_sha256="c" * 64,
        )


def test_evidence_requires_a_safe_source_url_and_keeps_field_locator() -> None:
    evidence = EvidenceRef(
        source_id="source:ministry-admission",
        source_observation_id="source-observation:" + "d" * 32,
        snapshot_sha256="c" * 64,
        source_url="https://official.example/admission/rules.pdf",
        locator=EvidenceLocator(page=3, table="minimum scores", row=4, field="minimum"),
    )
    assert evidence.has_structured_locator
    with pytest.raises(ValidationError, match="HTTPS"):
        EvidenceRef(
            source_id="source:ministry-admission",
            source_observation_id="source-observation:" + "d" * 32,
            snapshot_sha256="c" * 64,
            source_url="https://official.example/admission/rules.pdf?token=secret",
        )


def test_registry_recorded_time_and_observation_clock_order_are_checked() -> None:
    with pytest.raises(ValidationError, match="cannot precede approval"):
        _revision(approved_at=NOW, recorded_at=NOW - timedelta(minutes=1))
