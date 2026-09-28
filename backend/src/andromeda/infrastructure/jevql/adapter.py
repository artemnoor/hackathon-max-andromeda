"""Embedded-first adapter for rare, bounded semantic predicates."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Mapping
from decimal import Decimal

from andromeda.modules.analytics.contracts.semantic_predicate import (
    SemanticPredicateEvidence,
    SemanticPredicateFailureReason,
    SemanticPredicatePort,
    SemanticPredicateRequest,
    SemanticPredicateResult,
    SemanticPredicateStatus,
)

from .config import JevQLConfig, JevQLMode
from .transport import (
    EmbeddedTransport,
    JevQLTransport,
    JevQLTransportError,
    SharedServiceTransport,
)

logger = logging.getLogger("andromeda.infrastructure.jevql")


class JevQLAdapter(SemanticPredicatePort):
    def __init__(
        self,
        *,
        config: JevQLConfig | None = None,
        embedded: JevQLTransport | None = None,
        shared_service: JevQLTransport | None = None,
    ) -> None:
        self._config = config or JevQLConfig()
        self._embedded = embedded or EmbeddedTransport()
        self._shared_service = shared_service or (
            SharedServiceTransport(self._config) if self._config.shared_endpoint is not None else None
        )
        self._cache: dict[str, SemanticPredicateResult] = {}
        self._failures = 0
        self._circuit_open_until = 0.0

    def evaluate(self, request: SemanticPredicateRequest) -> SemanticPredicateResult:
        cache_identity = _cache_key(request)
        cached = self._cache.get(cache_identity)
        if cached is not None:
            logger.info("jevql_cache_hit definition_id=%s evaluated_population=%d", request.predicate.definition_id, cached.evaluated_population)
            return cached
        if time.monotonic() < self._circuit_open_until:
            return self._unavailable(request, SemanticPredicateFailureReason.CIRCUIT_OPEN, cache_identity)

        for mode, transport in self._transports():
            if transport is None or not transport.available():
                continue
            started = time.monotonic()
            logger.info(
                "jevql_request_started mode=%s definition_id=%s row_count=%d",
                mode.value,
                request.predicate.definition_id,
                len(request.rows),
            )
            try:
                raw = transport.evaluate(request)
                result = self._normalize(raw, request, cache_identity)
                self._failures = 0
                self._cache[cache_identity] = result
                logger.info(
                    "jevql_request_completed mode=%s definition_id=%s status=%s evaluated_population=%d latency_ms=%d",
                    mode.value,
                    request.predicate.definition_id,
                    result.status.value,
                    result.evaluated_population,
                    int((time.monotonic() - started) * 1000),
                )
                return result
            except JevQLTransportError as exc:
                self._failures += 1
                logger.warning(
                    "jevql_request_fallback mode=%s definition_id=%s failure_reason=%s",
                    mode.value,
                    request.predicate.definition_id,
                    exc.code,
                )
                if self._failures >= self._config.max_failures:
                    self._circuit_open_until = time.monotonic() + self._config.circuit_open_seconds
                continue
            except (TypeError, ValueError, KeyError) as exc:
                self._failures += 1
                logger.warning(
                    "jevql_schema_rejected mode=%s definition_id=%s error=%s",
                    mode.value,
                    request.predicate.definition_id,
                    type(exc).__name__,
                )
                continue
        return self._unavailable(request, SemanticPredicateFailureReason.CAPABILITY_UNAVAILABLE, cache_identity)

    def _transports(self) -> tuple[tuple[JevQLMode, JevQLTransport | None], ...]:
        configured = {
            JevQLMode.EMBEDDED: (JevQLMode.EMBEDDED, self._embedded),
            JevQLMode.SHARED_SERVICE: (JevQLMode.SHARED_SERVICE, self._shared_service),
        }
        if self._config.mode is JevQLMode.AUTO:
            return tuple(configured[mode] for mode in (JevQLMode.EMBEDDED, JevQLMode.SHARED_SERVICE))
        return (configured[self._config.mode],)

    def _normalize(
        self,
        raw: object,
        request: SemanticPredicateRequest,
        cache_identity: str,
    ) -> SemanticPredicateResult:
        if not isinstance(raw, Mapping):
            raise TypeError("jevQL result must be an object")
        raw_matches = raw.get("matches", {})
        if not isinstance(raw_matches, Mapping):
            raise TypeError("jevQL matches must be an object")
        row_ids = {row.canonical_id for row in request.rows}
        matches: dict[str, bool | None] = {}
        for row_id, value in raw_matches.items():
            if row_id not in row_ids or not isinstance(value, (bool, type(None))):
                raise ValueError("jevQL returned an unknown row or invalid predicate value")
            matches[row_id] = value
        evaluated = len(matches)
        status = SemanticPredicateStatus.AVAILABLE if evaluated == len(request.rows) else SemanticPredicateStatus.PARTIAL if evaluated else SemanticPredicateStatus.INSUFFICIENT_DATA
        confidence = raw.get("confidence", 0)
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("jevQL confidence is outside bounds")
        confidence_decimal = Decimal(str(confidence))
        evidence = tuple(
            SemanticPredicateEvidence(
                canonical_id=row.canonical_id,
                definition_id=request.predicate.definition_id,
                definition_version=request.predicate.definition_version,
                result=matches.get(row.canonical_id),
                confidence=confidence_decimal,
                status=status,
            )
            for row in request.rows
        )
        return SemanticPredicateResult(
            status=status,
            matches=matches,
            selected_ids=tuple(row_id for row_id, value in matches.items() if value is True),
            evaluated_population=evaluated,
            confidence=confidence_decimal,
            provider=str(raw.get("provider", "jevql")),
            model=str(raw.get("model", "unknown")),
            cache_identity=cache_identity,
            evidence=evidence,
        )

    @staticmethod
    def _unavailable(
        request: SemanticPredicateRequest,
        reason: SemanticPredicateFailureReason,
        cache_identity: str,
    ) -> SemanticPredicateResult:
        return SemanticPredicateResult(
            status=SemanticPredicateStatus.UNAVAILABLE,
            matches={row.canonical_id: None for row in request.rows},
            evaluated_population=0,
            provider="jevql",
            model="unknown",
            cache_identity=cache_identity,
            failure_reason=reason,
            evidence=tuple(
                SemanticPredicateEvidence(
                    canonical_id=row.canonical_id,
                    definition_id=request.predicate.definition_id,
                    definition_version=request.predicate.definition_version,
                    result=None,
                    status=SemanticPredicateStatus.UNAVAILABLE,
                    reason=reason,
                )
                for row in request.rows
            ),
        )


def _cache_key(request: SemanticPredicateRequest) -> str:
    payload = request.model_dump(mode="json")
    return "jevql:" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["JevQLAdapter"]
