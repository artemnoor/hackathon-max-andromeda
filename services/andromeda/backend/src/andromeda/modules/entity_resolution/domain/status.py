"""Status helpers kept separate from adapters and repositories."""

from ..contracts.public import ResolutionStatus


def is_resolved(status: ResolutionStatus) -> bool:
    return status in {ResolutionStatus.EXACT, ResolutionStatus.RESOLVED}


__all__ = ["ResolutionStatus", "is_resolved"]
