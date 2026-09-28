"""Ports implemented by backend adapters, never by transport clients."""

from __future__ import annotations

from typing import Protocol

from .public import (
    EntityResolutionCandidate,
    EntityResolutionResult,
    ResolutionContext,
    ResolutionEntityType,
)


class BoundedCandidateSelector(Protocol):
    """Select only among a source-backed candidate set; None means unresolved."""

    def select(
        self,
        query: str,
        candidates: tuple[EntityResolutionCandidate, ...],
    ) -> str | None: ...


class UniversityResolver(Protocol):
    def resolve(self, query: str, *, limit: int = 10) -> EntityResolutionResult: ...


class DirectionResolver(Protocol):
    def resolve(
        self,
        query: str,
        *,
        context: ResolutionContext | None = None,
        limit: int = 10,
    ) -> EntityResolutionResult: ...


class ProgramResolver(Protocol):
    def resolve(
        self,
        query: str,
        *,
        context: ResolutionContext | None = None,
        limit: int = 10,
    ) -> EntityResolutionResult: ...


class DisciplineResolver(Protocol):
    def resolve(self, query: str, *, limit: int = 10) -> EntityResolutionResult: ...


class MetricResolver(Protocol):
    def resolve(self, query: str, *, limit: int = 10) -> EntityResolutionResult: ...


class EntityResolverGateway(Protocol):
    """One transport-independent entry point for typed entity resolution."""

    def resolve(
        self,
        entity_type: ResolutionEntityType,
        query: str,
        *,
        context: ResolutionContext | None = None,
        limit: int = 10,
    ) -> EntityResolutionResult: ...


__all__ = [
    "BoundedCandidateSelector",
    "DirectionResolver",
    "DisciplineResolver",
    "EntityResolverGateway",
    "MetricResolver",
    "ProgramResolver",
    "UniversityResolver",
]
