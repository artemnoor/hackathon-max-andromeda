"""Auditable, read-only hypothetical policy review previews."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .approval import PolicyApprovalState
from .impact import PolicyImpactPreview
from .resolution import PolicyResolutionMode, ResolutionTrace
from .rule import PolicyRuleId
from .semantic_diff import PolicySemanticDiff

PolicyReviewPreviewId = Annotated[
    str, StringConstraints(pattern=r"^policy-review-preview:[a-f0-9]{64}$")
]


class PolicyReviewPreviewTarget(ContractModel):
    rule_id: PolicyRuleId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    revision_hash: SourceHash


class PolicyHypotheticalPreviewFields(ContractModel):
    schema_version: Literal["policy-hypothetical-preview.v1"] = (
        "policy-hypothetical-preview.v1"
    )
    hypothetical: Literal[True] = True
    approval_state: Literal[PolicyApprovalState.PENDING] = PolicyApprovalState.PENDING
    target: PolicyReviewPreviewTarget
    approved_snapshot_hash: SourceHash
    current_trace: ResolutionTrace
    candidate_trace: ResolutionTrace
    effective_diff: PolicySemanticDiff
    impact: PolicyImpactPreview
    calculated_at: datetime

    @field_validator("calculated_at")
    @classmethod
    def calculated_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("hypothetical preview timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def traces_are_exact_and_explicitly_hypothetical(
        self,
    ) -> PolicyHypotheticalPreviewFields:
        if self.current_trace.mode is not PolicyResolutionMode.APPROVED_EFFECTIVE:
            raise ValueError(
                "current preview trace must use only approved policy revisions"
            )
        if self.candidate_trace.mode is not PolicyResolutionMode.HYPOTHETICAL:
            raise ValueError("candidate preview trace must be explicitly hypothetical")
        if (
            self.current_trace.university_id != self.candidate_trace.university_id
            or self.current_trace.admission_year != self.candidate_trace.admission_year
            or self.current_trace.context_fingerprint
            != self.candidate_trace.context_fingerprint
        ):
            raise ValueError("policy preview traces must share one exact context")
        if (
            self.impact.current_trace_id != self.current_trace.trace_id
            or self.impact.candidate_trace_id != self.candidate_trace.trace_id
        ):
            raise ValueError("policy impact must reference both exact preview traces")
        if self.effective_diff.before_trace_id != self.current_trace.trace_id:
            raise ValueError("effective diff must reference the exact approved trace")
        if self.effective_diff.after_trace_id != self.candidate_trace.trace_id:
            raise ValueError(
                "effective diff must reference the exact hypothetical trace"
            )
        return self


class PolicyHypotheticalPreview(PolicyHypotheticalPreviewFields):
    preview_id: PolicyReviewPreviewId

    @model_validator(mode="after")
    def preview_identity_matches_payload(self) -> PolicyHypotheticalPreview:
        if self.preview_id != policy_hypothetical_preview_id(self):
            raise ValueError(
                "policy review preview ID does not match its structured result"
            )
        return self


def policy_hypothetical_preview_id(
    preview: PolicyHypotheticalPreview | PolicyHypotheticalPreviewFields,
) -> PolicyReviewPreviewId:
    def trace_payload(trace: ResolutionTrace) -> dict[str, object]:
        return {
            "mode": trace.mode.value,
            "university_id": trace.university_id,
            "admission_year": int(trace.admission_year),
            "cycle_id": trace.cycle_id,
            "cycle_revision": trace.cycle_revision,
            "cycle_evidence": [
                item.model_dump(mode="json") for item in trace.cycle_evidence
            ],
            "valid_as_of": trace.valid_as_of.isoformat() if trace.valid_as_of else None,
            "context_fingerprint": trace.context_fingerprint,
            "status": trace.status.value,
            "effective_rules": [
                item.model_dump(mode="json") for item in trace.effective_rules
            ],
            "conflicting_rules": [
                item.model_dump(mode="json") for item in trace.conflicting_rules
            ],
            "considered": [
                {
                    "rule_id": item.rule_id,
                    "revision": item.revision,
                    "revision_hash": item.revision_hash,
                    "filter_state": item.filter_state.value,
                    "reason": item.reason.value,
                }
                for item in trace.considered
            ],
        }

    impact = preview.impact
    payload = {
        "target": preview.target.model_dump(mode="json"),
        "approved_snapshot_hash": preview.approved_snapshot_hash,
        "current_trace": trace_payload(preview.current_trace),
        "candidate_trace": trace_payload(preview.candidate_trace),
        "effective_diff": {
            "status": preview.effective_diff.status.value,
            "changes": [
                item.model_dump(mode="json") for item in preview.effective_diff.changes
            ],
            "uncertainty_codes": preview.effective_diff.uncertainty_codes,
        },
        "impact": {
            "status": impact.status.value,
            "actionability": impact.actionability.value,
            "reason": impact.reason.value,
            "affected_objects": [
                item.model_dump(mode="json") for item in impact.affected_objects
            ],
            "domain_results": [
                item.model_dump(mode="json") for item in impact.domain_results
            ],
            "evidence": [item.model_dump(mode="json") for item in impact.evidence],
            "missing_input_codes": impact.missing_input_codes,
            "dependency_cycles": impact.dependency_cycles,
            "dependency_truncated": impact.dependency_truncated,
        },
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"policy-review-preview:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    )


__all__ = [
    "PolicyHypotheticalPreview",
    "PolicyHypotheticalPreviewFields",
    "PolicyReviewPreviewId",
    "PolicyReviewPreviewTarget",
    "policy_hypothetical_preview_id",
]
