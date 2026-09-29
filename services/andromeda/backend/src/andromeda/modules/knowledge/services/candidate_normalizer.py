"""Deterministic, bounded normalization of source text into review-only claims."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime

from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    Claim,
    ClaimedPolicyStage,
    ClaimEvidenceLink,
    ClaimEvidenceRelationship,
    ClaimExtractionMethod,
    ClaimReviewState,
    EvidenceLocator,
    EvidenceRef,
    SourceIdentity,
    SourceMilestones,
    SourceObservation,
    claim_id_for_source_assertion,
)

logger = logging.getLogger("andromeda.modules.knowledge.candidate_normalizer")

_MAX_DOCUMENT_CHARS = 2_000_000
_MAX_CLAIMS = 100
_MIN_ASSERTION_CHARS = 32
_MAX_ASSERTION_CHARS = 4_000
POLICY_CANDIDATE_PARSER_VERSION = "policy_text_lines:v1"
_POLICY_TERMS = re.compile(
    r"(?:\b(?:егэ|гия|бви)\b|олимпиад|поступлен|\bпри[её]м(?:а|е|у|ом)?\b|абитуриент|квот|"
    r"индивидуальн(?:ое|ых|ого)? достижен|проходн(?:ой|ые) балл|"
    r"минимальн(?:ый|ые) балл|вступительн(?:ый|ые) испытан)",
    re.IGNORECASE,
)


def normalize_policy_claim_candidates(
    document_text: str,
    *,
    source: SourceIdentity,
    observation: SourceObservation,
    recorded_at: datetime,
    limit: int = _MAX_CLAIMS,
) -> tuple[Claim, ...]:
    """Extract source assertions while leaving interpretation for human review.

    Source reliability is not copied onto a claim or used to infer policy status.
    """
    if not 1 <= limit <= _MAX_CLAIMS:
        raise ValueError(f"candidate limit must be between 1 and {_MAX_CLAIMS}")
    if len(document_text) > _MAX_DOCUMENT_CHARS:
        raise ValueError("normalized source text exceeds the configured character budget")
    if observation.source_id != source.source_id:
        raise ValueError("source observation does not belong to the supplied source identity")
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    if recorded_at < observation.captured_at:
        raise ValueError("recorded_at cannot precede capture")

    claims: list[Claim] = []
    seen: set[str] = set()
    offset = 0
    for raw_line in document_text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n").strip()
        start = offset + len(raw_line) - len(raw_line.lstrip())
        end = start + len(line)
        offset += len(raw_line)
        if not (_MIN_ASSERTION_CHARS <= len(line) <= _MAX_ASSERTION_CHARS):
            continue
        if not _POLICY_TERMS.search(line):
            continue
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        page = document_text.count("\f", 0, start) + 1 if "\f" in document_text else None
        claim_id = claim_id_for_source_assertion(
            observation.source_observation_id,
            start,
            end,
            digest,
        )
        evidence = EvidenceRef(
            source_id=source.source_id,
            source_observation_id=observation.source_observation_id,
            snapshot_sha256=observation.snapshot_sha256,
            source_url=observation.final_url,
            locator=EvidenceLocator(
                page=page,
                section="PDF extracted page" if page is not None else "deterministic text extraction",
                field="normalized_text_span",
                record_key=observation.snapshot_sha256,
            ),
        )
        claims.append(
            Claim(
                claim_id=claim_id,
                clock=BitemporalRevision(revision=1, recorded_at=recorded_at),
                source_observation_id=observation.source_observation_id,
                text_start_offset=start,
                text_end_offset=end,
                assertion_text=line,
                assertion_text_sha256=digest,
                proposition=None,
                claimed_stage=_claimed_stage(line),
                review_state=ClaimReviewState.NEEDS_REVIEW,
                source_milestones=SourceMilestones(captured_at=observation.captured_at),
                extraction_method=ClaimExtractionMethod.DETERMINISTIC_PARSER,
                extractor_id="policy_text_lines",
                extractor_version=POLICY_CANDIDATE_PARSER_VERSION,
                evidence=(
                    ClaimEvidenceLink(
                        relationship=ClaimEvidenceRelationship.ORIGINATES_FROM,
                        evidence=evidence,
                    ),
                ),
            )
        )
        if len(claims) >= limit:
            break
    logger.info(
        "knowledge_claim_candidates_normalized source_id=%s observation_id=%s claims=%d",
        source.source_id,
        observation.source_observation_id,
        len(claims),
    )
    return tuple(claims)


def _claimed_stage(assertion: str) -> ClaimedPolicyStage:
    normalized = assertion.casefold()
    if any(term in normalized for term in ("возможно", "слух", "обсуждается", "обсуждают")):
        return ClaimedPolicyStage.HYPOTHESIS
    if any(term in normalized for term in ("проект", "предлагается", "предложил")):
        return ClaimedPolicyStage.PROPOSAL
    if any(term in normalized for term in ("принят", "утвержден", "утверждён", "одобрен")):
        return ClaimedPolicyStage.ADOPTED
    if any(term in normalized for term in ("опубликован приказ", "опубликованы правила")):
        return ClaimedPolicyStage.PUBLISHED
    return ClaimedPolicyStage.UNKNOWN


__all__ = ["POLICY_CANDIDATE_PARSER_VERSION", "normalize_policy_claim_candidates"]
