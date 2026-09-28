from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from andromeda.infrastructure.jevql.adapter import JevQLAdapter
from andromeda.infrastructure.jevql.config import JevQLConfig
from andromeda.infrastructure.jevql.transport import (
    EmbeddedTransport,
    JevQLTransportError,
    SharedServiceTransport,
)
from andromeda.modules.analytics.contracts.semantic_predicate import (
    SemanticPredicate,
    SemanticPredicateRequest,
    SemanticPredicateRow,
    SemanticPredicateStatus,
)


def _request() -> SemanticPredicateRequest:
    return SemanticPredicateRequest(
        predicate=SemanticPredicate(
            definition_id="discipline-fit.v1",
            definition_version="semantic-taxonomy.v1",
            question="Does this discipline involve applied programming?",
            allowed_fields=("discipline_name",),
        ),
        rows=(SemanticPredicateRow(canonical_id="discipline:one", fields={"discipline_name": "Python"}),),
    )


class _FakeTransport:
    def __init__(self, available: bool, response: object) -> None:
        self._available = available
        self.response = response
        self.calls = 0

    def available(self) -> bool:
        return self._available

    def evaluate(self, request: SemanticPredicateRequest) -> object:
        self.calls += 1
        return self.response


def test_shared_service_is_not_selected_when_embedded_is_available() -> None:
    embedded = _FakeTransport(
        True,
        {"matches": {"discipline:one": True}, "confidence": 0.9},
    )
    shared = _FakeTransport(True, {"matches": {}, "confidence": 0.0})
    result = JevQLAdapter(
        config=JevQLConfig(mode="auto"),
        embedded=embedded,
        shared_service=shared,
    ).evaluate(_request())

    assert result.status is SemanticPredicateStatus.AVAILABLE
    assert embedded.calls == 1
    assert shared.calls == 0


def test_embedded_transport_calls_upstream_jevql_judge_api() -> None:
    class UpstreamClient:
        def judge(self, question, rows, *, kind, raw):
            assert question.startswith("Does this")
            assert rows[0]["canonical_id"] == "discipline:one"
            assert kind == "noul"
            assert raw is True
            return SimpleNamespace(
                answers=[SimpleNamespace(p=0.97, passed=True, confidence=0.91)],
            )

    transport = EmbeddedTransport(client_factory=UpstreamClient)
    result = transport.evaluate(_request())

    assert result["matches"] == {"discipline:one": True}
    assert result["provider"] == "jevql"


def test_embedded_transport_preserves_false_and_missing_confidence() -> None:
    class UpstreamClient:
        def judge(self, question, rows, *, kind, raw):
            return SimpleNamespace(
                answers=[SimpleNamespace(p=0.08, passed=False, confidence=None)],
            )

    result = EmbeddedTransport(client_factory=UpstreamClient).evaluate(_request())

    assert result["matches"] == {"discipline:one": False}
    assert result["confidence"] == 0.0


def test_embedded_transport_marks_missing_upstream_answer_unknown() -> None:
    class UpstreamClient:
        def judge(self, question, rows, *, kind, raw):
            return SimpleNamespace(answers=[])

    result = EmbeddedTransport(client_factory=UpstreamClient).evaluate(_request())

    assert result["matches"] == {"discipline:one": None}
    assert result["confidence"] == 0.0


def test_embedded_transport_rejects_answers_for_unknown_rows() -> None:
    class UpstreamClient:
        def judge(self, question, rows, *, kind, raw):
            return SimpleNamespace(
                answers=[
                    SimpleNamespace(p=0.9, passed=True, confidence=0.9),
                    SimpleNamespace(p=0.1, passed=False, confidence=0.9),
                ],
            )

    with pytest.raises(JevQLTransportError, match="unknown rows"):
        EmbeddedTransport(client_factory=UpstreamClient).evaluate(_request())


def test_embedded_transport_rejects_malformed_upstream_answer() -> None:
    class UpstreamClient:
        def judge(self, question, rows, *, kind, raw):
            return SimpleNamespace(
                answers=[SimpleNamespace(p=0.5, passed="yes", confidence=0.5)],
            )

    with pytest.raises(JevQLTransportError, match="non-boolean answer"):
        EmbeddedTransport(client_factory=UpstreamClient).evaluate(_request())


def test_pinned_upstream_jevql_judge_contract() -> None:
    jevql = pytest.importorskip("jevql")
    signature = inspect.signature(jevql.Jevql.judge)

    assert signature.parameters["kind"].default == "noul"
    assert {"p", "passed", "confidence"}.issubset(jevql.JudgeAnswer.__dataclass_fields__)
    assert jevql.JudgeAnswer.from_dict({"p": 0.75, "pass": True, "confidence": 0.88}).passed is True


def test_shared_transport_constructs_upstream_jevql_url_client() -> None:
    captured = {}

    class UpstreamClient:
        def judge(self, question, rows, *, kind, raw):
            return SimpleNamespace(answers=[SimpleNamespace(passed=False, confidence=0.8)])

    def factory():
        captured["constructed"] = True
        return UpstreamClient()

    transport = SharedServiceTransport(
        JevQLConfig(mode="shared_service", shared_endpoint="http://jevql:7433", shared_allowed_hosts=("jevql",)),
        client_factory=factory,
    )
    result = transport.evaluate(_request())

    assert captured["constructed"] is True
    assert result["matches"] == {"discipline:one": False}
