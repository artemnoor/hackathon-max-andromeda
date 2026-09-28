"""Versioned exact-assertion identity for safe review clustering."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime
from decimal import Decimal

from andromeda.modules.knowledge.contracts.public import (
    Claim,
    ClaimCandidateCluster,
    ClaimCandidateClusterId,
    ClaimFingerprint,
    ClaimRevisionRef,
)

CLAIM_FINGERPRINT_VERSION = "exact_assertion:v1"


def fingerprint_claim(claim: Claim) -> ClaimFingerprint:
    """Hash exact normalized assertion plus typed subject/stage/time dimensions."""
    milestones = claim.source_milestones
    proposition = claim.proposition.model_dump(mode="json") if claim.proposition else None
    if proposition is not None and proposition["value"]["kind"] == "decimal":
        proposition["value"]["value"] = _canonical_decimal(proposition["value"]["value"])
    identity = {
        "assertion": " ".join(unicodedata.normalize("NFKC", claim.assertion_text).casefold().split()),
        "claimed_stage": claim.claimed_stage.value,
        "effective_time": _interval_identity(
            milestones.effective_time.start if milestones.effective_time else None,
            milestones.effective_time.end if milestones.effective_time else None,
        ),
        "proposition": proposition,
        "valid_time": _interval_identity(
            claim.clock.valid_time.start if claim.clock.valid_time else None,
            claim.clock.valid_time.end if claim.clock.valid_time else None,
        ),
        "version": CLAIM_FINGERPRINT_VERSION,
    }
    serialized = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"claim-fingerprint:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def _canonical_decimal(value: str) -> str:
    decimal = Decimal(value).normalize()
    return format(decimal, "f")


def cluster_id_for_fingerprint(fingerprint: ClaimFingerprint) -> ClaimCandidateClusterId:
    digest = hashlib.sha256(fingerprint.encode("ascii")).hexdigest()
    return f"claim-cluster:{digest}"


def build_claim_cluster(
    fingerprint: ClaimFingerprint,
    members: tuple[ClaimRevisionRef, ...],
) -> ClaimCandidateCluster:
    return ClaimCandidateCluster(
        cluster_id=cluster_id_for_fingerprint(fingerprint),
        fingerprint=fingerprint,
        fingerprint_version=CLAIM_FINGERPRINT_VERSION,
        members=members,
    )


def _interval_identity(
    start: datetime | None, end: datetime | None
) -> tuple[str | None, str | None] | None:
    if start is None and end is None:
        return None
    return (
        start.isoformat() if start is not None else None,
        end.isoformat() if end is not None else None,
    )


__all__ = [
    "CLAIM_FINGERPRINT_VERSION",
    "build_claim_cluster",
    "cluster_id_for_fingerprint",
    "fingerprint_claim",
]
