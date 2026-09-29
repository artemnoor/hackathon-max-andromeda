from __future__ import annotations

from decimal import Decimal

import pytest

from andromeda.infrastructure.jevql.adapter import JevQLAdapter
from andromeda.infrastructure.jevql.config import JevQLConfig
from andromeda.modules.analytics.contracts.semantic_predicate import (
    SemanticPredicate,
    SemanticPredicateRequest,
    SemanticPredicateRow,
    SemanticPredicateStatus,
)
from andromeda.modules.analytics.domain.metric_registry import MetricRegistry


def _request() -> SemanticPredicateRequest:
    return SemanticPredicateRequest(
        predicate=SemanticPredicate(
            definition_id="discipline-fit.v1",
            definition_version="semantic-taxonomy.v1",
            question="Does this discipline involve applied programming?",
            allowed_fields=("discipline_name", "course_block"),
            max_rows=2,
        ),
        rows=(
            SemanticPredicateRow(canonical_id="discipline:one", fields={"discipline_name": "Python"}),
            SemanticPredicateRow(canonical_id="discipline:two", fields={"discipline_name": "History"}),
        ),
    )


def test_predicate_contract_rejects_sql_and_unbounded_rows() -> None:
    with pytest.raises(ValueError, match="SQL"):
        SemanticPredicate(
            definition_id="unsafe.v1",
            definition_version="semantic-taxonomy.v1",
            question="SELECT * FROM disciplines",
            allowed_fields=("discipline_name",),
        )
    with pytest.raises(ValueError, match="row budget"):
        SemanticPredicateRequest(
            predicate=SemanticPredicate(
                definition_id="bounded.v1",
                definition_version="semantic-taxonomy.v1",
                question="Does this match?",
                allowed_fields=("discipline_name",),
                max_rows=1,
            ),
            rows=(
                SemanticPredicateRow(canonical_id="discipline:one", fields={"discipline_name": "A"}),
                SemanticPredicateRow(canonical_id="discipline:two", fields={"discipline_name": "B"}),
            ),
        )


class _FakeTransport:
    def __init__(self, available: bool, response: object | None = None) -> None:
        self._available = available
        self.response = response
        self.calls = 0

    def available(self) -> bool:
        return self._available

    def evaluate(self, request: SemanticPredicateRequest) -> object:
        self.calls += 1
        return self.response


def test_embedded_is_preferred_then_shared_fallback_and_cache_is_bounded() -> None:
    embedded = _FakeTransport(False)
    shared = _FakeTransport(
        True,
        {
            "matches": {"discipline:one": True, "discipline:two": None},
            "confidence": 0.75,
            "provider": "jevql-shared",
            "model": "jevql-test",
        },
    )
    adapter = JevQLAdapter(
        config=JevQLConfig(mode="auto", max_rows=2),
        embedded=embedded,
        shared_service=shared,
    )

    first = adapter.evaluate(_request())
    second = adapter.evaluate(_request())

    assert first.status is SemanticPredicateStatus.AVAILABLE
    assert first.selected_ids == ("discipline:one",)
    assert first.matches["discipline:two"] is None
    assert first.confidence == Decimal("0.75")
    assert first.evidence[1].result is None
    assert second.cache_identity == first.cache_identity
    assert shared.calls == 1
    assert embedded.calls == 0


def test_unavailable_does_not_turn_unassessed_rows_into_false() -> None:
    adapter = JevQLAdapter(
        config=JevQLConfig(mode="embedded"),
        embedded=_FakeTransport(False),
    )

    result = adapter.evaluate(_request())

    assert result.status is SemanticPredicateStatus.UNAVAILABLE
    assert all(value is None for value in result.matches.values())
    assert result.selected_ids == ()


def test_shared_endpoint_must_be_allow_listed() -> None:
    with pytest.raises(ValueError, match="allow-listed"):
        JevQLConfig(
            shared_endpoint="http://169.254.169.254/latest",
            shared_allowed_hosts=("localhost",),
        )


def test_default_metric_registry_does_not_enable_predicates() -> None:
    assert all(metric.predicate_definition_id is None for metric in MetricRegistry().all())
