"""Conservative exact clustering and deterministic claim candidate diffs."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from andromeda.modules.knowledge.contracts.public import (
    Claim,
    ClaimDiffEntry,
    ClaimDiffKind,
    ClaimFieldChange,
    ClaimRevisionRef,
    ClaimSetDiff,
    SourceObservationDiff,
    SourcePollAttempt,
    SourcePollOutcome,
)
from andromeda.modules.knowledge.domain.claim_fingerprint import fingerprint_claim


def diff_claim_sets(before: tuple[Claim, ...], after: tuple[Claim, ...]) -> ClaimSetDiff:
    """Pair exact claims, then only compare changes with an unambiguous typed identity."""
    old = _group_by_fingerprint(before)
    new = _group_by_fingerprint(after)
    entries: list[ClaimDiffEntry] = []
    for fingerprint in sorted(old.keys() | new.keys()):
        old_group = old.get(fingerprint, [])
        new_group = new.get(fingerprint, [])
        if old_group and new_group:
            entries.append(
                ClaimDiffEntry(
                    kind=ClaimDiffKind.UNCHANGED,
                    before=tuple(_ref(item) for item in sorted(old_group, key=_claim_key)),
                    after=tuple(_ref(item) for item in sorted(new_group, key=_claim_key)),
                    reason_code="exact_assertion_match",
                )
            )

    unmatched_before, unmatched_after = _unmatched(before, after, old, new)
    old_identities = _group_by_typed_identity(unmatched_before)
    new_identities = _group_by_typed_identity(unmatched_after)
    paired_old: set[tuple[str, int]] = set()
    paired_new: set[tuple[str, int]] = set()
    for identity in sorted(old_identities.keys() & new_identities.keys()):
        old_group = old_identities[identity]
        new_group = new_identities[identity]
        if len(old_group) == len(new_group) == 1:
            old_claim, new_claim = old_group[0], new_group[0]
            changes = _typed_field_changes(old_claim, new_claim)
            if changes:
                entries.append(
                    ClaimDiffEntry(
                        kind=ClaimDiffKind.REVISED,
                        before=(_ref(old_claim),),
                        after=(_ref(new_claim),),
                        changes=changes,
                        reason_code="same_typed_subject_value_changed",
                    )
                )
                paired_old.add((old_claim.claim_id, old_claim.clock.revision))
                paired_new.add((new_claim.claim_id, new_claim.clock.revision))
        elif old_group and new_group:
            entries.append(
                ClaimDiffEntry(
                    kind=ClaimDiffKind.AMBIGUOUS,
                    before=tuple(_ref(item) for item in sorted(old_group, key=_claim_key)),
                    after=tuple(_ref(item) for item in sorted(new_group, key=_claim_key)),
                    reason_code="multiple_typed_identity_matches",
                )
            )
            paired_old.update(_claim_key(item) for item in old_group)
            paired_new.update(_claim_key(item) for item in new_group)

    remaining_old = [item for item in unmatched_before if _claim_key(item) not in paired_old]
    remaining_new = [item for item in unmatched_after if _claim_key(item) not in paired_new]
    if remaining_old:
        entries.append(
            ClaimDiffEntry(
                kind=ClaimDiffKind.REMOVED,
                before=tuple(_ref(item) for item in sorted(remaining_old, key=_claim_key)),
                reason_code="assertion_not_present_in_new_snapshot",
            )
        )
    if remaining_new:
        entries.append(
            ClaimDiffEntry(
                kind=ClaimDiffKind.ADDED,
                after=tuple(_ref(item) for item in sorted(remaining_new, key=_claim_key)),
                reason_code="new_source_assertion",
            )
        )
    return ClaimSetDiff(entries=tuple(entries))


def diff_source_attempt(
    previous: SourcePollAttempt | None,
    current: SourcePollAttempt,
    *,
    before_claims: tuple[Claim, ...] = (),
    after_claims: tuple[Claim, ...] = (),
) -> SourceObservationDiff:
    """Create source and candidate diff while keeping unavailability distinct from removal."""
    if previous is not None:
        if previous.source_id != current.source_id:
            raise ValueError("source attempts must refer to the same source")
        if previous.completed_at > current.started_at:
            raise ValueError("source attempts are not in chronological order")
        if current.previous_snapshot_sha256 != previous.last_successful_snapshot_sha256:
            raise ValueError("current source attempt was based on a stale successful snapshot")
    successful = current.outcome in {
        SourcePollOutcome.NEW,
        SourcePollOutcome.CHANGED,
        SourcePollOutcome.UNCHANGED,
    }
    if not successful and (before_claims or after_claims):
        raise ValueError("unavailable capture cannot be used to infer claim removals")
    if current.outcome is SourcePollOutcome.NEW and before_claims:
        raise ValueError("new source content cannot have claims from a prior snapshot")
    if previous is not None and previous.source_observation_id is not None and any(
        claim.source_observation_id != previous.source_observation_id
        for claim in before_claims
    ):
        raise ValueError("prior claims must match the previous source observation")
    if successful and current.source_observation_id is not None and any(
        claim.source_observation_id != current.source_observation_id
        for claim in after_claims
    ):
        raise ValueError("current claims must match the current source observation")
    if any(
        link.evidence.source_id != current.source_id
        for claim in (*before_claims, *after_claims)
        for link in claim.evidence
    ):
        raise ValueError("source diff claims must belong to the polled source")
    prior_hash = current.previous_snapshot_sha256
    if prior_hash is None and previous is not None:
        prior_hash = previous.last_successful_snapshot_sha256
    prior_observation = previous.source_observation_id if previous is not None else None
    return SourceObservationDiff(
        source_id=current.source_id,
        current_attempt_outcome=current.outcome,
        previous_snapshot_sha256=prior_hash,
        snapshot_sha256=current.snapshot_sha256,
        last_successful_snapshot_sha256=current.last_successful_snapshot_sha256,
        previous_observation_id=prior_observation,
        current_observation_id=current.source_observation_id,
        claim_diff=diff_claim_sets(before_claims, after_claims) if successful else None,
    )


def _group_by_fingerprint(claims: tuple[Claim, ...]) -> dict[str, list[Claim]]:
    groups: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        groups[fingerprint_claim(claim)].append(claim)
    return groups


def _unmatched(
    before: tuple[Claim, ...],
    after: tuple[Claim, ...],
    old_groups: dict[str, list[Claim]],
    new_groups: dict[str, list[Claim]],
) -> tuple[list[Claim], list[Claim]]:
    matched = old_groups.keys() & new_groups.keys()
    old_keys = {_claim_key(item) for key in matched for item in old_groups[key]}
    new_keys = {_claim_key(item) for key in matched for item in new_groups[key]}
    return (
        [item for item in before if _claim_key(item) not in old_keys],
        [item for item in after if _claim_key(item) not in new_keys],
    )


def _group_by_typed_identity(claims: list[Claim]) -> dict[str, list[Claim]]:
    groups: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        if claim.proposition is None:
            continue
        proposition = claim.proposition
        identity = {
            "predicate": proposition.predicate,
            "subject_id": proposition.subject_id,
            "subject_kind": proposition.subject_kind.value,
            "unit": proposition.unit,
        }
        key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        groups[key].append(claim)
    return groups


def _typed_field_changes(before: Claim, after: Claim) -> tuple[ClaimFieldChange, ...]:
    assert before.proposition is not None and after.proposition is not None
    changes: list[ClaimFieldChange] = []
    for path, old, new in (
        ("assertion_text", before.assertion_text, after.assertion_text),
        ("proposition.value", _serialize(before.proposition.value.model_dump(mode="json")), _serialize(after.proposition.value.model_dump(mode="json"))),
        ("claimed_stage", before.claimed_stage.value, after.claimed_stage.value),
        (
            "valid_time.start",
            _time_identity(before.clock.valid_time.start) if before.clock.valid_time else None,
            _time_identity(after.clock.valid_time.start) if after.clock.valid_time else None,
        ),
        (
            "valid_time.end",
            _time_identity(before.clock.valid_time.end) if before.clock.valid_time else None,
            _time_identity(after.clock.valid_time.end) if after.clock.valid_time else None,
        ),
        (
            "effective_time.start",
            _time_identity(before.source_milestones.effective_time.start)
            if before.source_milestones.effective_time
            else None,
            _time_identity(after.source_milestones.effective_time.start)
            if after.source_milestones.effective_time
            else None,
        ),
        (
            "effective_time.end",
            _time_identity(before.source_milestones.effective_time.end)
            if before.source_milestones.effective_time
            else None,
            _time_identity(after.source_milestones.effective_time.end)
            if after.source_milestones.effective_time
            else None,
        ),
    ):
        if old != new:
            changes.append(ClaimFieldChange(path=path, before=old, after=new))
    return tuple(changes)


def _serialize(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _interval_identity(start: datetime | None, end: datetime | None) -> tuple[str | None, str | None] | None:
    if start is None and end is None:
        return None
    return (_time_identity(start), _time_identity(end))


def _time_identity(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _ref(claim: Claim) -> ClaimRevisionRef:
    return ClaimRevisionRef(claim_id=claim.claim_id, revision=claim.clock.revision)


def _claim_key(claim: Claim) -> tuple[str, int]:
    return (claim.claim_id, claim.clock.revision)


__all__ = [
    "diff_claim_sets",
    "diff_source_attempt",
]
