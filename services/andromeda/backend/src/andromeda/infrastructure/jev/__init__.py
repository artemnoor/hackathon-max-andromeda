"""Optional external decision-model adapters.

The package intentionally contains no Jev SDK import. A provider-specific
transport can be injected by the composition root when it is explicitly
enabled; deterministic fallback remains the default.
"""

from .adapter import JevAdapterConfig, JevDecisionModelAdapter, JevTransport
from .contracts import (
    JevFailure,
    JevFailureReason,
    JevRequestEnvelope,
    JevResponseEnvelope,
    JevUsage,
    ModelIdentity,
)
from .question_registry import QuestionRegistry, QuestionRegistryError
from .typesafe_client import TypeSafeJevTransport
from .runtime import JevCapabilityReport, build_decision_policy

__all__ = [
    "JevAdapterConfig",
    "JevDecisionModelAdapter",
    "JevTransport",
    "JevFailure",
    "JevFailureReason",
    "JevRequestEnvelope",
    "JevResponseEnvelope",
    "JevUsage",
    "ModelIdentity",
    "QuestionRegistry",
    "QuestionRegistryError",
    "TypeSafeJevTransport",
    "JevCapabilityReport",
    "build_decision_policy",
]
