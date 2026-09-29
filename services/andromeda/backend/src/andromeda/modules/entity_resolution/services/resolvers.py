"""Deterministic, cached entity resolvers shared by API and channels."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from andromeda.modules.admission_benefits.contracts.public import (
    Olympiad,
    OlympiadProfile,
)
from andromeda.modules.admission_benefits.repository.ports import AdmissionBenefitReader
from andromeda.modules.analytics.domain.metric_registry import MetricRegistry
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.universities.contracts.public import Direction, University

from ..contracts.ports import BoundedCandidateSelector
from ..contracts.public import (
    CandidateMatchReason,
    EntityResolutionCandidate,
    EntityResolutionResult,
    ResolutionContext,
    ResolutionEntityType,
    ResolutionStatus,
)
from .hierarchical import HierarchicalResolutionService
from .normalization import (
    aliases_for,
    direction_university_id,
    normalize_text,
    program_university_id,
    tokens,
)

logger = logging.getLogger("andromeda.modules.entity_resolution.olympiad")


class CachedEntityCatalog:
    """TTL cache preventing a catalog SQL query on every conversational turn."""

    def __init__(
        self,
        reader: Any,
        *,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("catalog ttl must be positive")
        self._reader = reader
        self._ttl = ttl_seconds
        self._clock = clock
        self._loaded_at = 0.0
        self._universities: tuple[University, ...] | None = None
        self._directions: tuple[Direction, ...] | None = None
        self._programs: tuple[Program, ...] | None = None
        self._disciplines: tuple[Discipline, ...] | None = None

    def universities(self) -> tuple[University, ...]:
        self._refresh_if_needed()
        if self._universities is None:
            self._universities = tuple(self._reader.list_universities())
        return self._universities

    def directions(self) -> tuple[Direction, ...]:
        self._refresh_if_needed()
        if self._directions is None:
            self._directions = tuple(self._reader.list_directions())
        return self._directions

    def programs(self) -> tuple[Program, ...]:
        self._refresh_if_needed()
        if self._programs is None:
            self._programs = tuple(self._reader.list_programs())
        return self._programs

    def disciplines(self) -> tuple[Discipline, ...]:
        self._refresh_if_needed()
        if self._disciplines is None:
            self._disciplines = tuple(self._reader.list_disciplines())
        return self._disciplines

    def refresh(self) -> None:
        self._universities = tuple(self._reader.list_universities())
        self._directions = tuple(self._reader.list_directions())
        self._programs = tuple(self._reader.list_programs())
        self._disciplines = tuple(self._reader.list_disciplines())
        self._loaded_at = self._clock()

    def _refresh_if_needed(self) -> None:
        if self._loaded_at == 0.0 or self._clock() - self._loaded_at >= self._ttl:
            self.refresh()


@dataclass(frozen=True, slots=True)
class _Match:
    canonical_id: str
    label: str
    code: str | None
    reason: CandidateMatchReason
    score: Decimal
    university_id: str | None = None
    direction_id: str | None = None
    parent_id: str | None = None
    admission_year: int | None = None
    profile_name: str | None = None


class UniversityResolverService:
    def __init__(self, catalog: CachedEntityCatalog) -> None:
        self._catalog = catalog

    def resolve(self, query: str, *, limit: int = 10) -> EntityResolutionResult:
        matches = (
            _match_entity(
                query,
                entity_type=ResolutionEntityType.UNIVERSITY,
                canonical_id=item.id,
                label=item.name,
                code=None,
                aliases=aliases_for(entity_id=item.id, entity_name=item.name),
            )
            for item in self._catalog.universities()
        )
        return _result(ResolutionEntityType.UNIVERSITY, query, matches, limit)


class DirectionResolverService:
    def __init__(self, catalog: CachedEntityCatalog) -> None:
        self._catalog = catalog

    def resolve(
        self, query: str, *, context: ResolutionContext | None = None, limit: int = 10
    ) -> EntityResolutionResult:
        items = self._catalog.directions()
        if context and context.university_id:
            items = tuple(
                item for item in items if item.university_id == context.university_id
            )
        matches = (
            _match_entity(
                query,
                entity_type=ResolutionEntityType.DIRECTION,
                canonical_id=item.id,
                label=item.name,
                code=item.code,
                aliases=aliases_for(
                    entity_id=item.id, code=item.code, entity_name=item.name
                ),
                university_id=item.university_id,
            )
            for item in items
        )
        return _result(ResolutionEntityType.DIRECTION, query, matches, limit)


class ProgramResolverService:
    def __init__(self, catalog: CachedEntityCatalog) -> None:
        self._catalog = catalog

    def resolve(
        self, query: str, *, context: ResolutionContext | None = None, limit: int = 10
    ) -> EntityResolutionResult:
        items = self._catalog.programs()
        if context and context.direction_id:
            items = tuple(
                item for item in items if item.direction_id == context.direction_id
            )
        elif context and context.university_id:
            items = tuple(
                item
                for item in items
                if direction_university_id(item.direction_id) == context.university_id
                or program_university_id(item.id) == context.university_id
            )
        matches = (
            _match_entity(
                query,
                entity_type=ResolutionEntityType.PROGRAM,
                canonical_id=item.id,
                label=item.name,
                code=item.code,
                aliases=aliases_for(
                    entity_id=item.id, code=item.code, entity_name=item.name
                ),
                university_id=program_university_id(item.id)
                or direction_university_id(item.direction_id),
                direction_id=item.direction_id,
            )
            for item in items
        )
        return _result(ResolutionEntityType.PROGRAM, query, matches, limit)


class DisciplineResolverService:
    def __init__(self, catalog: CachedEntityCatalog) -> None:
        self._catalog = catalog

    def resolve(self, query: str, *, limit: int = 10) -> EntityResolutionResult:
        matches = (
            _match_entity(
                query,
                entity_type=ResolutionEntityType.DISCIPLINE,
                canonical_id=item.id,
                label=item.name,
                code=None,
                aliases=aliases_for(entity_id=item.id, entity_name=item.name),
            )
            for item in self._catalog.disciplines()
        )
        return _result(ResolutionEntityType.DISCIPLINE, query, matches, limit)


class MetricResolverService:
    def __init__(self, registry: MetricRegistry | None = None) -> None:
        self._registry = registry or MetricRegistry()

    def resolve(self, query: str, *, limit: int = 10) -> EntityResolutionResult:
        matches = (
            _match_entity(
                query,
                entity_type=ResolutionEntityType.METRIC,
                canonical_id=f"metric:{item.code}",
                label=item.name,
                code=item.code,
                aliases=aliases_for(entity_id=f"metric:{item.code}"),
            )
            for item in self._registry.all()
        )
        return _result(ResolutionEntityType.METRIC, query, matches, limit)


class EntityResolverService:
    """Dispatch typed resolution without exposing implementations to callers."""

    def __init__(
        self,
        catalog: CachedEntityCatalog,
        registry: MetricRegistry | None = None,
        hierarchical: HierarchicalResolutionService | None = None,
        admission_benefit_reader: AdmissionBenefitReader | None = None,
        candidate_selector: BoundedCandidateSelector | None = None,
    ) -> None:
        self._universities = UniversityResolverService(catalog)
        self._directions = DirectionResolverService(catalog)
        self._programs = ProgramResolverService(catalog)
        self._disciplines = DisciplineResolverService(catalog)
        self._metrics = MetricResolverService(registry)
        self._hierarchical = hierarchical
        self._admission_benefit_reader = admission_benefit_reader
        self._candidate_selector = candidate_selector

    def resolve(
        self,
        entity_type: ResolutionEntityType,
        query: str,
        *,
        context: ResolutionContext | None = None,
        limit: int = 10,
    ) -> EntityResolutionResult:
        if limit < 1 or limit > 1000:
            raise ValueError("resolution limit must be between 1 and 1000")
        resolver_limit = (
            min(self._hierarchical.candidate_threshold + 1, 1000)
            if self._hierarchical is not None
            else limit
        )
        if entity_type in {
            ResolutionEntityType.OLYMPIAD,
            ResolutionEntityType.OLYMPIAD_PROFILE,
        }:
            result = self._resolve_admission_benefit_entity(
                entity_type, query, context=context, limit=resolver_limit
            )
            return _trim_result(result, limit)
        if entity_type is ResolutionEntityType.UNIVERSITY:
            result = self._universities.resolve(query, limit=resolver_limit)
        elif entity_type is ResolutionEntityType.DIRECTION:
            result = self._directions.resolve(
                query, context=context, limit=resolver_limit
            )
        elif entity_type is ResolutionEntityType.PROGRAM:
            result = self._programs.resolve(
                query, context=context, limit=resolver_limit
            )
        elif entity_type is ResolutionEntityType.DISCIPLINE:
            result = self._disciplines.resolve(query, limit=resolver_limit)
        else:
            result = self._metrics.resolve(query, limit=resolver_limit)
        if (
            self._hierarchical is not None
            and len(result.candidates) > self._hierarchical.candidate_threshold
        ):
            result = self._hierarchical.resolve(entity_type, query, result.candidates)
        return _trim_result(result, limit)

    def _resolve_admission_benefit_entity(
        self,
        entity_type: ResolutionEntityType,
        query: str,
        *,
        context: ResolutionContext | None,
        limit: int,
    ) -> EntityResolutionResult:
        if (
            self._admission_benefit_reader is None
            or context is None
            or context.university_id is None
            or context.admission_year is None
        ):
            return EntityResolutionResult(
                entity_type=entity_type,
                query=query,
                status=ResolutionStatus.NOT_FOUND,
                resolution_evidence={
                    "required_context": "university_id_and_admission_year"
                },
            )
        snapshot = self._admission_benefit_reader.get_catalog(
            context.university_id, context.admission_year
        )
        if snapshot is None:
            return EntityResolutionResult(
                entity_type=entity_type,
                query=query,
                status=ResolutionStatus.NOT_FOUND,
                resolution_evidence={"reason": "source_backed_catalog_missing"},
            )

        if entity_type is ResolutionEntityType.OLYMPIAD:
            source_candidates = tuple(
                _olympiad_match(item, context.university_id)
                for item in snapshot.olympiads
            )
            exact = tuple(
                item
                for item in source_candidates
                if normalize_text(query) == normalize_text(item.label)
            )
            if exact:
                return _candidate_result(entity_type, query, exact, exact=True)
            candidates = _narrow_candidates(query, source_candidates, limit)
        else:
            olympiads_by_id = {item.id: item for item in snapshot.olympiads}
            source_candidates = tuple(
                _profile_match(
                    profile,
                    olympiads_by_id.get(profile.olympiad_id),
                    context.university_id,
                )
                for profile in snapshot.olympiad_profiles
            )
            normalized_query = normalize_text(query)
            exact = tuple(
                item
                for item in source_candidates
                if normalized_query
                in {
                    normalize_text(item.label),
                    normalize_text(item.profile_name or ""),
                }
            )
            if exact:
                return _candidate_result(entity_type, query, exact, exact=True)

            profile_matches = _narrow_candidates(query, source_candidates, limit)
            if len(profile_matches) == 1:
                return _candidate_result(
                    entity_type,
                    query,
                    profile_matches,
                    selected_id=profile_matches[0].canonical_id,
                )

            # First narrow by the official Olympiad name, then let the bounded
            # candidate selector distinguish that Olympiad's official profiles.
            olympiad_matches = _narrow_candidates(
                query,
                tuple(
                    _olympiad_match(item, context.university_id)
                    for item in snapshot.olympiads
                ),
                limit,
            )
            matched_olympiad_ids = {item.canonical_id for item in olympiad_matches}
            if matched_olympiad_ids:
                candidates = tuple(
                    item
                    for item in source_candidates
                    if item.parent_id in matched_olympiad_ids
                )
            else:
                candidates = _narrow_candidates(query, source_candidates, limit)
            candidates = tuple(sorted(candidates, key=lambda item: item.canonical_id))[
                :limit
            ]

        if not candidates:
            return EntityResolutionResult(
                entity_type=entity_type,
                query=query,
                status=ResolutionStatus.NOT_FOUND,
            )
        candidate_result = _candidate_result(entity_type, query, candidates)
        public_candidates = candidate_result.candidates
        if self._candidate_selector is not None and 1 < len(public_candidates) <= 8:
            selected_id = self._candidate_selector.select(query, public_candidates)
            if selected_id in {item.canonical_id for item in public_candidates}:
                logger.info(
                    "admission_entity_resolution entity_type=%s year=%s candidates=%d source=jev outcome=resolved",
                    entity_type.value,
                    context.admission_year,
                    len(public_candidates),
                )
                return candidate_result.model_copy(
                    update={
                        "status": ResolutionStatus.RESOLVED,
                        "selected_id": selected_id,
                        "resolution_strategy": "jev_candidate",
                        "resolution_evidence": {
                            "decision_source": "jev",
                            "candidate_count": str(len(public_candidates)),
                        },
                    }
                )
        logger.info(
            "admission_entity_resolution entity_type=%s year=%s candidates=%d source=deterministic outcome=%s",
            entity_type.value,
            context.admission_year,
            len(public_candidates),
            "ambiguous" if candidates else "not_found",
        )
        return candidate_result


def _match_entity(
    query: str,
    *,
    entity_type: ResolutionEntityType,
    canonical_id: str,
    label: str,
    code: str | None,
    aliases: Iterable[str],
    university_id: str | None = None,
    direction_id: str | None = None,
) -> _Match | None:
    normalized_query = normalize_text(query)
    normalized_id = normalize_text(canonical_id)
    normalized_code = normalize_text(code) if code else None
    normalized_label = normalize_text(label)
    normalized_aliases = {normalize_text(alias) for alias in aliases}
    if normalized_query == normalized_id:
        reason, score = CandidateMatchReason.CANONICAL_ID, Decimal("1")
    elif normalized_code and normalized_query == normalized_code:
        reason, score = CandidateMatchReason.CODE, Decimal("1")
    elif normalized_query == normalized_label:
        reason, score = CandidateMatchReason.NAME, Decimal("0.95")
    elif normalized_query in normalized_aliases:
        reason, score = CandidateMatchReason.ALIAS, Decimal("0.90")
    else:
        query_tokens = tokens(normalized_query)
        candidate_tokens = tokens(
            f"{normalized_id} {normalized_code or ''} {normalized_label}"
        )
        if not query_tokens or not query_tokens.issubset(candidate_tokens):
            return None
        reason, score = CandidateMatchReason.TOKEN_MATCH, Decimal("0.70")
    return _Match(canonical_id, label, code, reason, score, university_id, direction_id)


def _olympiad_match(item: Olympiad, university_id: str) -> _Match:
    return _Match(
        canonical_id=item.id,
        label=item.official_name,
        code=None,
        reason=CandidateMatchReason.TOKEN_MATCH,
        score=Decimal("0.70"),
        university_id=university_id,
        admission_year=item.admission_year,
    )


def _profile_match(
    item: OlympiadProfile,
    olympiad: Olympiad | None,
    university_id: str,
) -> _Match:
    olympiad_name = olympiad.official_name if olympiad is not None else item.olympiad_id
    return _Match(
        canonical_id=item.id,
        label=f"{olympiad_name} — {item.profile_name}",
        code=None,
        reason=CandidateMatchReason.TOKEN_MATCH,
        score=Decimal("0.70"),
        university_id=university_id,
        parent_id=item.olympiad_id,
        admission_year=item.admission_year,
        profile_name=item.profile_name,
    )


_ENTITY_QUERY_STOP_WORDS = frozenset(
    {
        "в",
        "и",
        "я",
        "по",
        "на",
        "для",
        "мне",
        "мой",
        "моя",
        "призер",
        "призёр",
        "победитель",
        "олимпиада",
        "олимпиады",
        "профиль",
        "профилю",
        "направление",
        "направлению",
    }
)


def _narrow_candidates(
    query: str,
    candidates: tuple[_Match, ...],
    limit: int,
) -> tuple[_Match, ...]:
    query_terms = {
        item
        for item in tokens(query)
        if len(item) >= 4 and item not in _ENTITY_QUERY_STOP_WORDS
    }
    ranked: list[tuple[int, _Match]] = []
    for candidate in candidates:
        candidate_terms = tokens(candidate.label)
        overlap = sum(
            any(
                term == candidate_term
                or (
                    min(len(term), len(candidate_term)) >= 4
                    and (
                        term.startswith(candidate_term)
                        or candidate_term.startswith(term)
                    )
                )
                for candidate_term in candidate_terms
            )
            for term in query_terms
        )
        if overlap:
            ranked.append((overlap, candidate))
    if not ranked:
        return ()
    best = max(score for score, _ in ranked)
    selected = tuple(
        _Match(
            canonical_id=item.canonical_id,
            label=item.label,
            code=item.code,
            reason=CandidateMatchReason.TOKEN_MATCH,
            score=Decimal("0.70")
            + Decimal(best) / Decimal(max(len(query_terms), 1)) / Decimal(10),
            university_id=item.university_id,
            direction_id=item.direction_id,
            parent_id=item.parent_id,
            admission_year=item.admission_year,
            profile_name=item.profile_name,
        )
        for score, item in ranked
        if score == best
    )
    return tuple(sorted(selected, key=lambda item: item.canonical_id)[:limit])


def _candidate_result(
    entity_type: ResolutionEntityType,
    query: str,
    matches: tuple[_Match, ...],
    *,
    exact: bool = False,
    selected_id: str | None = None,
) -> EntityResolutionResult:
    candidates = tuple(
        EntityResolutionCandidate(
            entity_type=entity_type,
            canonical_id=item.canonical_id,
            label=item.label,
            match_reason=(CandidateMatchReason.NAME if exact else item.reason),
            score=Decimal("0.95") if exact else item.score,
            confidence=Decimal("0.95") if exact else item.score,
            university_id=item.university_id,
            code=item.code,
            parent_id=item.parent_id,
            admission_year=item.admission_year,
        )
        for item in matches
    )
    if not candidates:
        return EntityResolutionResult(
            entity_type=entity_type,
            query=query,
            status=ResolutionStatus.NOT_FOUND,
        )
    if selected_id is not None:
        return EntityResolutionResult(
            entity_type=entity_type,
            query=query,
            status=ResolutionStatus.RESOLVED,
            candidates=candidates,
            selected_id=selected_id,
        )
    if exact and len(candidates) == 1:
        return EntityResolutionResult(
            entity_type=entity_type,
            query=query,
            status=ResolutionStatus.EXACT,
            candidates=candidates,
            selected_id=candidates[0].canonical_id,
        )
    return EntityResolutionResult(
        entity_type=entity_type,
        query=query,
        status=ResolutionStatus.AMBIGUOUS,
        candidates=candidates,
    )


def _result(
    entity_type: ResolutionEntityType,
    query: str,
    matches: Iterable[_Match | None],
    limit: int,
) -> EntityResolutionResult:
    if limit < 1 or limit > 1000:
        raise ValueError("resolution limit must be between 1 and 1000")
    ranked = sorted(
        (match for match in matches if match is not None),
        key=lambda item: (-item.score, item.canonical_id),
    )
    candidates = tuple(
        EntityResolutionCandidate(
            entity_type=entity_type,
            canonical_id=item.canonical_id,
            label=item.label,
            match_reason=item.reason,
            score=item.score,
            confidence=item.score,
            university_id=item.university_id,
            direction_id=item.direction_id,
            parent_id=item.parent_id,
            admission_year=item.admission_year,
            code=item.code,
        )
        for item in ranked[:limit]
    )
    if not candidates:
        return EntityResolutionResult(
            entity_type=entity_type, query=query, status=ResolutionStatus.NOT_FOUND
        )
    plausible = tuple(
        candidate
        for candidate in candidates
        if candidate.score >= candidates[0].score - Decimal("0.05")
    )
    if len(plausible) > 1:
        return EntityResolutionResult(
            entity_type=entity_type,
            query=query,
            status=ResolutionStatus.AMBIGUOUS,
            candidates=candidates,
        )
    status = (
        ResolutionStatus.EXACT
        if candidates[0].match_reason is CandidateMatchReason.CANONICAL_ID
        else ResolutionStatus.RESOLVED
    )
    return EntityResolutionResult(
        entity_type=entity_type,
        query=query,
        status=status,
        candidates=candidates,
        selected_id=candidates[0].canonical_id,
    )


def _trim_result(result: EntityResolutionResult, limit: int) -> EntityResolutionResult:
    """Keep the public result bounded while retaining a model-selected leaf."""

    candidates = list(result.candidates[:limit])
    if result.selected_id is not None and result.selected_id not in {
        item.canonical_id for item in candidates
    }:
        selected = next(
            (
                item
                for item in result.candidates
                if item.canonical_id == result.selected_id
            ),
            None,
        )
        if selected is not None:
            if candidates:
                candidates[-1] = selected
            else:
                candidates.append(selected)
    return result.model_copy(update={"candidates": tuple(candidates)})


__all__ = [
    "CachedEntityCatalog",
    "DirectionResolverService",
    "DisciplineResolverService",
    "EntityResolverService",
    "MetricResolverService",
    "ProgramResolverService",
    "UniversityResolverService",
]
