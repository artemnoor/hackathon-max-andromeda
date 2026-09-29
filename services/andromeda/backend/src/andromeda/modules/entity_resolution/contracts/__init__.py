"""Public contracts and ports for entity resolution."""

from .ports import (
    DirectionResolver,
    DisciplineResolver,
    EntityResolverGateway,
    MetricResolver,
    ProgramResolver,
    UniversityResolver,
)
from .public import (
    CandidateMatchReason,
    EntityResolutionCandidate,
    EntityResolutionResult,
    ResolutionContext,
    ResolutionEntityType,
    ResolutionStatus,
)
from .hierarchical import (
    HierarchicalSelectionPort,
    SelectionFailureReason,
    SelectionNode,
    SelectionRequest,
    SelectionResult,
    SelectionTree,
)

__all__ = [
    "CandidateMatchReason",
    "DirectionResolver",
    "DisciplineResolver",
    "EntityResolverGateway",
    "EntityResolutionCandidate",
    "EntityResolutionResult",
    "HierarchicalSelectionPort",
    "MetricResolver",
    "ProgramResolver",
    "ResolutionContext",
    "ResolutionEntityType",
    "ResolutionStatus",
    "SelectionFailureReason",
    "SelectionNode",
    "SelectionRequest",
    "SelectionResult",
    "SelectionTree",
    "UniversityResolver",
]
