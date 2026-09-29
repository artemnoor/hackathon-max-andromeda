"""Cross-module conflict gate for exact policy approval decisions."""

from __future__ import annotations

from andromeda.infrastructure.repositories.knowledge_conflicts import (
    SqlAlchemyConflictGroupRepository,
)
from andromeda.modules.knowledge.contracts.public import (
    ConflictParticipantKind,
    ConflictParticipantReference,
    KnowledgeConflictState,
)
from andromeda.modules.policy.repository.ports import PolicyApprovalConflictReader
from andromeda.shared.contracts.ids import SourceHash


class SqlAlchemyPolicyApprovalConflictReader(PolicyApprovalConflictReader):
    """Reads at most 101 exact policy conflict memberships; overflow blocks approval."""

    def __init__(self, conflicts: SqlAlchemyConflictGroupRepository) -> None:
        self._conflicts = conflicts

    def has_open_conflicts(
        self,
        rule_id: str,
        revision: int,
        revision_hash: SourceHash,
    ) -> bool:
        groups = self._conflicts.list_for_participant(
            ConflictParticipantReference(
                kind=ConflictParticipantKind.POLICY_RULE_REVISION,
                object_id=rule_id,
                revision=revision,
                content_hash=revision_hash,
            ),
            limit=100,
        )
        return len(groups) > 100 or any(
            group.state is KnowledgeConflictState.OPEN for group in groups
        )


__all__ = ["SqlAlchemyPolicyApprovalConflictReader"]
