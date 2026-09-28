"""Transport-independent entity resolution for conversational and API clients."""

from .contracts.public import (
    CandidateMatchReason,
    EntityResolutionCandidate,
    EntityResolutionResult,
    ResolutionContext,
    ResolutionEntityType,
    ResolutionStatus,
)
from .services.resolvers import EntityResolverService
from .services.hierarchical import HierarchicalResolutionService

__all__ = [
    "CandidateMatchReason",
    "EntityResolutionCandidate",
    "EntityResolutionResult",
    "EntityResolverService",
    "HierarchicalResolutionService",
    "ResolutionContext",
    "ResolutionEntityType",
    "ResolutionStatus",
]
