from pathlib import Path
from types import SimpleNamespace

import httpx

from andromeda.infrastructure.jev.contracts import JevRequestEnvelope
from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from andromeda.infrastructure.jev.typesafe_client import (
    TypeSafeJevTransport,
    _dynamic_options,
    _evidence_for,
    _payload_for,
)
from andromeda.modules.conversation.contracts.decision_definitions import (
    DecisionDefinitionKind,
    DecisionOutputSchema,
    DecisionPiiPolicy,
    DecisionTimeoutClass,
)
from andromeda.modules.conversation.contracts.policy import (
    DecisionModelOperation,
    DecisionModelSource,
)

ROOT = Path(__file__).parents[2]
REGISTRY = QuestionRegistry.from_file(ROOT / "config/jev/question-definitions.v1.yaml")


class _FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.models = SimpleNamespace(
            list=lambda **_: SimpleNamespace(
                models=(SimpleNamespace(name="jev-latest"),)
            )
        )
        self.last_state = None
        self.last_questions = None

    def system_one(self, *, state, questions, **_):
        self.last_state = state
        self.last_questions = questions
        return SimpleNamespace(
            model="jev-latest-2026-09",
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
            choices={"answer": SimpleNamespace(choice="math", confidence=0.91)},
        )


def _request() -> JevRequestEnvelope:
    return JevRequestEnvelope(
        definition_id="metric.v1",
        definition_version="metric-definition.v1",
        definition_kind=DecisionDefinitionKind.METRIC,
        operation=DecisionModelOperation.RESOLVE_METRIC,
        redacted_payload={"text": "математика", "candidates": ("math", "physics")},
        correlation_id="jev:test",
        timeout_seconds=2.0,
        timeout_class=DecisionTimeoutClass.INTERACTIVE,
        pii_policy=DecisionPiiPolicy.SANITIZED,
        output_schema=DecisionOutputSchema(fields=("metric_code",)),
    )


def test_official_sdk_adapter_sends_only_registered_typed_question() -> None:
    holder = {}

    def factory(**kwargs):
        holder["client"] = _FakeClient(**kwargs)
        return holder["client"]

    transport = TypeSafeJevTransport(
        api_key="secret-key",
        endpoint="https://api.typesafe.ai",
        model="jev-latest",
        registry=REGISTRY,
        client_factory=factory,
    )
    response = transport.request_envelope(_request())

    assert response.identity.provider == "typesafe"
    assert response.identity.source is DecisionModelSource.JEV
    assert response.payload == {
        "metric_code": "math",
        "candidates": ("math",),
        "confidence": "high",
    }
    assert set(holder["client"].last_questions) == {"answer"}
    question = holder["client"].last_questions["answer"]
    assert question.model_dump(mode="json")["criteria"] == {
        "math": "math",
        "physics": "physics",
        "unresolved": "The phrase does not identify one supplied metric.",
    }
    assert transport.health_check() is True


def test_metric_resolution_can_choose_unresolved_without_inventing_a_metric() -> None:
    definition = REGISTRY.get("metric.v1")
    options = _dynamic_options(
        definition, {"candidates": ("mathematics_share", "physics_share")}
    )
    payload = _payload_for(
        definition,
        SimpleNamespace(
            choices={"answer": SimpleNamespace(choice="unresolved", confidence=0.7)}
        ),
    )

    assert set(options) == {"mathematics_share", "physics_share", "unresolved"}
    assert payload["metric_code"] is None


def test_official_sdk_noul_answers_preserve_raw_feature_probabilities() -> None:
    response = SimpleNamespace(
        choices={},
        answers={
            "mathematics": SimpleNamespace(noul=0.93),
            "programming": SimpleNamespace(noul=0.08),
            "invalid": SimpleNamespace(noul=1.2),
        },
    )

    evidence = _evidence_for(response)

    assert evidence is not None
    assert evidence.answer_kind == "noul_batch"
    assert evidence.answer_value == {"mathematics": 0.93, "programming": 0.08}
    assert evidence.probabilities == {"mathematics": 0.93, "programming": 0.08}
    assert evidence.has_probability_evidence is True


def test_client_rejects_non_https_provider_endpoint() -> None:
    try:
        TypeSafeJevTransport(
            api_key="secret-key",
            endpoint="http://evil.example",
            model="jev-latest",
            registry=REGISTRY,
        )
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("non-HTTPS endpoint must be rejected")


def test_polza_health_check_accepts_its_openai_compatible_model_list(
    monkeypatch,
) -> None:
    calls = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {"object": "list", "data": [{"id": "typesafe/jev"}]}

    def fake_get(url, *, headers, timeout):
        calls.update(url=url, headers=headers, timeout=timeout)
        return _Response()

    monkeypatch.setattr(httpx, "get", fake_get)
    transport = TypeSafeJevTransport(
        api_key="secret-key",
        endpoint="https://polza.ai/api",
        model="typesafe/jev",
        registry=REGISTRY,
    )

    assert transport.health_check() is True
    assert calls["url"] == "https://polza.ai/api/v1/models"
    assert calls["headers"] == {"Authorization": "Bearer secret-key"}
    assert calls["timeout"] == 2.0


def test_intent_provider_vocabulary_maps_to_domain_without_rewriting_evidence() -> None:
    definition = REGISTRY.get("intent.v1")
    probabilities = {
        "catalog_search": 0.05,
        "comparison": 0.83,
        "admission_search": 0.04,
        "recommendation": 0.02,
        "unknown": 0.06,
    }

    class IntentClient(_FakeClient):
        def system_one(self, *, state, questions, **_):
            self.last_state = state
            self.last_questions = questions
            return SimpleNamespace(
                model="jev-live-contract-test",
                usage=SimpleNamespace(input_tokens=10, output_tokens=2),
                choices={
                    "answer": SimpleNamespace(
                        choice="comparison",
                        confidence=0.83,
                        probabilities=probabilities,
                    )
                },
            )

    transport = TypeSafeJevTransport(
        api_key="test-only",
        endpoint="https://polza.ai/api",
        model="typesafe/jev",
        registry=REGISTRY,
        client_factory=lambda **kwargs: IntentClient(**kwargs),
    )
    response = transport.request_envelope(
        JevRequestEnvelope(
            definition_id=definition.definition_id,
            definition_version=definition.version,
            definition_kind=definition.kind,
            operation=DecisionModelOperation.RESOLVE_INTENT,
            redacted_payload={"text": "Сравни две программы"},
            correlation_id="jev:test-intent-vocabulary",
            timeout_seconds=2.0,
            timeout_class=definition.timeout_class,
            pii_policy=definition.pii_policy,
            output_schema=definition.output_schema,
        )
    )

    assert response.payload == {"intent": "compare_programs", "confidence": "high"}
    assert response.evidence is not None
    assert response.evidence.answer_value == "comparison"
    assert response.evidence.probabilities == probabilities


def test_registered_but_unsupported_recommendation_intent_fails_safe_to_unknown() -> (
    None
):
    definition = REGISTRY.get("intent.v1")

    class RecommendationClient(_FakeClient):
        def system_one(self, *, state, questions, **_):
            return SimpleNamespace(
                model="jev-live-contract-test",
                usage=SimpleNamespace(input_tokens=10, output_tokens=2),
                choices={
                    "answer": SimpleNamespace(
                        choice="recommendation",
                        confidence=0.9,
                        probabilities={
                            "catalog_search": 0.01,
                            "comparison": 0.01,
                            "admission_search": 0.01,
                            "recommendation": 0.90,
                            "unknown": 0.07,
                        },
                    )
                },
            )

    transport = TypeSafeJevTransport(
        api_key="test-only",
        endpoint="https://polza.ai/api",
        model="typesafe/jev",
        registry=REGISTRY,
        client_factory=lambda **kwargs: RecommendationClient(**kwargs),
    )
    response = transport.request_envelope(
        JevRequestEnvelope(
            definition_id=definition.definition_id,
            definition_version=definition.version,
            definition_kind=definition.kind,
            operation=DecisionModelOperation.RESOLVE_INTENT,
            redacted_payload={"text": "Посоветуй программу"},
            correlation_id="jev:test-unsupported-intent",
            timeout_seconds=2.0,
            timeout_class=definition.timeout_class,
            pii_policy=definition.pii_policy,
            output_schema=definition.output_schema,
        )
    )

    assert response.payload == {"intent": "unknown", "confidence": "high"}
    assert response.evidence is not None
    assert response.evidence.answer_value == "recommendation"


def test_polza_health_check_fails_closed_when_model_is_not_listed(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {"object": "list", "data": [{"id": "another-model"}]}

    monkeypatch.setattr(httpx, "get", lambda *_args, **_kwargs: _Response())
    transport = TypeSafeJevTransport(
        api_key="secret-key",
        endpoint="https://polza.ai/api",
        model="typesafe/jev",
        registry=REGISTRY,
    )

    assert transport.health_check() is False


def test_health_check_fails_closed_when_optional_sdk_is_missing(monkeypatch) -> None:
    from andromeda.infrastructure.jev import typesafe_client

    def missing_sdk(_module_name):
        raise ImportError("optional SDK unavailable")

    monkeypatch.setattr(typesafe_client.importlib, "import_module", missing_sdk)
    transport = TypeSafeJevTransport(
        api_key="test-only",
        endpoint="https://api.typesafe.ai",
        model="typesafe/jev",
        registry=REGISTRY,
    )

    assert transport.health_check() is False


def test_official_sdk_uses_only_supplied_olympiad_profile_choices() -> None:
    registry = QuestionRegistry.from_file(
        ROOT / "config/jev/question-definitions.admission.v1.yaml"
    )
    holder = {}

    class ResolutionClient(_FakeClient):
        def system_one(self, *, state, questions, **_):
            self.last_state = state
            self.last_questions = questions
            return SimpleNamespace(
                model="jev-admission-test",
                usage=SimpleNamespace(input_tokens=8, output_tokens=1),
                choices={
                    "answer": SimpleNamespace(
                        choice="olympiad-profile:shag-engineering",
                        confidence=0.95,
                    )
                },
            )

    def factory(**kwargs):
        holder["client"] = ResolutionClient(**kwargs)
        return holder["client"]

    transport = TypeSafeJevTransport(
        api_key="secret-key",
        endpoint="https://polza.ai/api",
        model="typesafe/jev",
        registry=registry,
        client_factory=factory,
    )
    request = JevRequestEnvelope(
        definition_id="olympiad-profile-resolution.v1",
        definition_version="olympiad-profile-resolution-definition.v1",
        definition_kind=DecisionDefinitionKind.ENTITY_RESOLUTION,
        operation=DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE,
        redacted_payload={
            "text": "шаг будущее инженерное дело",
            "candidates": (
                {
                    "candidate_id": "olympiad-profile:shag-engineering",
                    "label": "Шаг в будущее — Инженерное дело",
                },
                {
                    "candidate_id": "olympiad-profile:shag-programming",
                    "label": "Шаг в будущее — Программирование",
                },
            ),
        },
        correlation_id="jev:test-admission-resolution",
        timeout_seconds=2.0,
        timeout_class=DecisionTimeoutClass.INTERACTIVE,
        pii_policy=DecisionPiiPolicy.SANITIZED,
        output_schema=DecisionOutputSchema(fields=("candidate_id", "confidence")),
    )

    response = transport.request_envelope(request)
    client = holder["client"]

    assert response.payload == {
        "candidate_id": "olympiad-profile:shag-engineering",
        "confidence": "high",
    }
    assert client.last_questions["answer"].model_dump(mode="json")["criteria"] == {
        "olympiad-profile:shag-engineering": "Шаг в будущее — Инженерное дело",
        "olympiad-profile:shag-programming": "Шаг в будущее — Программирование",
        "unresolved": "The phrase does not identify one supplied candidate.",
    }
    assert client.last_state["text"] == "шаг будущее инженерное дело"
