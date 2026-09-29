"""Pure factories and invariants for immutable policy rule revisions."""

from __future__ import annotations

from andromeda.modules.policy.contracts.rule import (
    PolicyRuleRevision,
    PolicyRuleRevisionFields,
    policy_rule_content_hash,
)
from andromeda.modules.policy.domain.field_registry import validate_selector_ast


def create_policy_rule_revision(fields: PolicyRuleRevisionFields) -> PolicyRuleRevision:
    validate_selector_ast(fields.selector)
    return PolicyRuleRevision(
        **fields.model_dump(mode="python"),
        content_hash=policy_rule_content_hash(fields),
    )


__all__ = ["create_policy_rule_revision"]
