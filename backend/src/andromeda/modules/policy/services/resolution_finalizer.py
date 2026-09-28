"""Apply the shared deterministic precedence result to an exact trace."""

from __future__ import annotations

from andromeda.modules.policy.contracts.applicability import PolicySelection
from andromeda.modules.policy.contracts.precedence import PolicyPrecedenceResult
from andromeda.modules.policy.contracts.resolution import (
    PolicyResolutionBlocker,
    PolicyResolutionStatus,
    ResolutionTrace,
    ResolutionTraceFields,
    policy_resolution_trace_id,
)


def apply_precedence_result(
    trace: ResolutionTrace,
    result: PolicyPrecedenceResult,
) -> ResolutionTrace:
    if result.status == "resolved":
        status = PolicyResolutionStatus.RESOLVED
        effective_rules = result.effective_rules
        conflicting_rules: tuple[PolicySelection, ...] = ()
    elif result.status == "conflict":
        status = PolicyResolutionStatus.CONFLICT
        effective_rules = ()
        conflicting_rules = result.conflicting_rules
    else:
        status = PolicyResolutionStatus.INDETERMINATE
        effective_rules = ()
        conflicting_rules = ()

    values = trace.model_dump(mode="python", exclude={"trace_id"})
    blockers = set(trace.blockers)
    if result.truncated:
        blockers.add(PolicyResolutionBlocker.PRECEDENCE_DECISION_LIMIT)
    values.update(
        status=status,
        effective_rules=effective_rules,
        conflicting_rules=conflicting_rules,
        precedence_decisions=result.decisions,
        blockers=tuple(sorted(blockers)),
    )
    fields = ResolutionTraceFields(**values)
    return ResolutionTrace(
        **fields.model_dump(mode="python"),
        trace_id=policy_resolution_trace_id(fields),
    )


def mark_resolution_indeterminate(
    trace: ResolutionTrace,
    *,
    blocker: PolicyResolutionBlocker | None = None,
) -> ResolutionTrace:
    values = trace.model_dump(mode="python", exclude={"trace_id"})
    blockers = set(trace.blockers)
    if blocker is not None:
        blockers.add(blocker)
    values.update(
        status=PolicyResolutionStatus.INDETERMINATE,
        effective_rules=(),
        conflicting_rules=(),
        precedence_decisions=(),
        blockers=tuple(sorted(blockers)),
    )
    fields = ResolutionTraceFields(**values)
    return ResolutionTrace(
        **fields.model_dump(mode="python"),
        trace_id=policy_resolution_trace_id(fields),
    )


__all__ = ["apply_precedence_result", "mark_resolution_indeterminate"]
