from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from andromeda.infrastructure.jev.adapter import (
    JevAdapterConfig,
    JevDecisionModelAdapter,
)
from andromeda.infrastructure.jev.contracts import (
    JevAnswerEvidence,
    JevFailureReason,
    JevRequestEnvelope,
    JevResponseEnvelope,
    JevUsage,
    ModelIdentity,
)
from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from andromeda.modules.conversation.contracts.policy import (
    CandidateResolutionOption,
    DecisionAction,
    DecisionModelOperation,
    DecisionModelSource,
)
from andromeda.modules.conversation.contracts.public import (
    ConversationIntent,
    ConversationSlot,
    NextAction,
    QuerySession,
)
from andromeda.modules.conversation.services.decision_model import (
    RuleBasedDecisionModel,
)
from andromeda.modules.presentation.contracts.policy import ResponseRequest
from andromeda.modules.proftest.contracts.public import ProfileScope


class _UnavailableTransport:
    def request(
        self, operation: str, payload: Mapping[str, object], *, timeout_seconds: float
    ) -> object:
        raise TimeoutError(operation)


class _InvalidTransport:
    def request(
        self, operation: str, payload: Mapping[str, object], *, timeout_seconds: float
    ) -> object:
        if operation == "resolve_intent":
            return {"intent": "execute_sql", "source": "jev", "confidence": "high"}
        return {"response_format": "text", "template": "<script>bad</script>"}


class _EnvelopeTransport:
    def __init__(self) -> None:
        self.requests: list[JevRequestEnvelope] = []

    def request_envelope(self, request: JevRequestEnvelope) -> object:
        self.requests.append(request)
        return JevResponseEnvelope(
            payload={
                "intent": "analytics_query",
                "source": "jev",
                "confidence": "high",
            },
            identity=ModelIdentity(
                model_version="jev-observed-test",
                artifact_id="intent.v1@intent-definition.v1",
            ),
        )


class _RejectedCalibration:
    artifact_id = "fixture-artifact"

    def evaluate(
        self,
        definition_id: str,
        evidence: JevAnswerEvidence,
        *,
        model_version: str | None = None,
    ):
        del model_version
        assert definition_id == "intent.v1"
        assert evidence.answer_value == "analytics_query"
        return type(
            "Gate",
            (),
            {
                "accepted": False,
                "artifact_id": self.artifact_id,
                "reason": "calibration_rejected",
            },
        )()


class _AcceptedCandidateCalibration:
    artifact_id = "admission-fixture-artifact"

    def evaluate(
        self,
        definition_id: str,
        evidence: JevAnswerEvidence,
        *,
        model_version: str | None = None,
    ):
        del model_version
        assert definition_id == "olympiad-profile-resolution.v1"
        assert evidence.answer_value == "olympiad-profile:shag-engineering"
        return type(
            "Gate",
            (),
            {"accepted": True, "artifact_id": self.artifact_id, "reason": "accepted"},
        )()


def test_jev_unavailable_falls_back_without_changing_deterministic_intent() -> None:
    adapter = JevDecisionModelAdapter(
        _UnavailableTransport(),
        RuleBasedDecisionModel(),
        config=JevAdapterConfig(max_retries=0),
    )

    decision = adapter.resolve_intent("Где больше математики?")

    assert decision.source is DecisionModelSource.FALLBACK
    assert decision.intent.value == "analytics_query"
    assert decision.fallback_reason == "provider_unavailable"


def test_timeout_auth_and_provider_errors_fail_closed() -> None:
    failure_cases = (
        (TimeoutError("provider timeout"), "provider_unavailable"),
        (PermissionError("provider auth"), "provider_unavailable"),
        (RuntimeError("provider 500"), "provider_unavailable"),
    )

    for error, expected_reason in failure_cases:

        class FailingTransport:
            def request(self, operation, payload, *, timeout_seconds, error=error):
                del operation, payload, timeout_seconds
                raise error

        adapter = JevDecisionModelAdapter(
            FailingTransport(),
            RuleBasedDecisionModel(),
            config=JevAdapterConfig(max_retries=0),
        )

        decision = adapter.resolve_intent("Где больше математики?")

        assert decision.source is DecisionModelSource.FALLBACK
        assert decision.intent.value == "analytics_query"
        assert decision.fallback_reason == expected_reason


def test_repeated_provider_failure_opens_circuit_without_more_calls() -> None:
    class FailingTransport:
        calls = 0

        def request(self, operation, payload, *, timeout_seconds):
            del operation, payload, timeout_seconds
            self.calls += 1
            raise RuntimeError("provider unavailable")

    transport = FailingTransport()
    adapter = JevDecisionModelAdapter(
        transport,
        RuleBasedDecisionModel(),
        config=JevAdapterConfig(max_retries=0, max_failures=1),
    )

    first = adapter.resolve_intent("Где больше математики?")
    second = adapter.resolve_intent("Где больше физики?")

    assert first.source is DecisionModelSource.FALLBACK
    assert second.source is DecisionModelSource.FALLBACK
    assert second.fallback_reason == "provider_unavailable"
    assert transport.calls == 1


def test_invalid_provider_intent_and_template_are_not_trusted() -> None:
    adapter = JevDecisionModelAdapter(_InvalidTransport(), RuleBasedDecisionModel())

    intent = adapter.resolve_intent("Где больше математики?")
    presentation = adapter.choose_presentation(ResponseRequest())

    assert intent.source is DecisionModelSource.FALLBACK
    assert intent.intent.value == "analytics_query"
    assert presentation.source is DecisionModelSource.FALLBACK
    assert presentation.template == "analytics-summary"


def test_typed_transport_receives_registry_definition_and_schema() -> None:
    transport = _EnvelopeTransport()
    registry = QuestionRegistry.from_file(
        Path(__file__).resolve().parents[2]
        / "config"
        / "jev"
        / "question-definitions.v1.yaml"
    )
    adapter = JevDecisionModelAdapter(
        transport, RuleBasedDecisionModel(), registry=registry
    )

    decision = adapter.resolve_intent("Где больше математики?")

    assert decision.source is DecisionModelSource.JEV
    assert decision.model_version == "jev-observed-test"
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.definition_id == "intent.v1"
    assert request.definition_version == "intent-definition.v1"
    assert request.operation is DecisionModelOperation.RESOLVE_INTENT
    assert request.output_schema.fields == ("intent", "confidence")
    assert request.timeout_class.value == "interactive"


def test_missing_registry_artifact_is_a_typed_fallback() -> None:
    registry = QuestionRegistry.from_document(
        {
            "definitions": [
                {
                    "definition_id": "intent.v1",
                    "kind": "intent",
                    "operation": "resolve_intent",
                    "version": "intent-definition.v1",
                    "instructions": "test",
                    "output_schema": {"fields": ["intent"]},
                    "deterministic_fallback": "rule_based_intent",
                    "timeout_class": "interactive",
                    "pii_policy": "sanitized",
                    "evaluation_dataset_key": "test.intent.v1",
                }
            ]
        }
    )
    adapter = JevDecisionModelAdapter(
        _EnvelopeTransport(), RuleBasedDecisionModel(), registry=registry
    )

    decision = adapter.resolve_metric("математика", candidates=("mathematics_share",))

    assert decision.source is DecisionModelSource.FALLBACK
    assert decision.fallback_reason == JevFailureReason.ARTIFACT_MISSING.value


def test_calibration_gate_rejects_provider_answer_before_domain_parsing() -> None:
    class Transport:
        def request_envelope(self, request: JevRequestEnvelope) -> JevResponseEnvelope:
            return JevResponseEnvelope(
                payload={
                    "intent": "analytics_query",
                    "source": "jev",
                    "confidence": "high",
                },
                identity=ModelIdentity(artifact_id="intent.v1@intent-definition.v1"),
                usage=JevUsage(),
                evidence=JevAnswerEvidence(
                    answer_kind="choice",
                    answer_value="analytics_query",
                    probabilities={"analytics_query": 0.6, "unknown": 0.4},
                    has_probability_evidence=True,
                ),
            )

    adapter = JevDecisionModelAdapter(
        Transport(),
        RuleBasedDecisionModel(),
        calibration=_RejectedCalibration(),
    )

    decision = adapter.resolve_intent("Где больше математики?")

    assert decision.source is DecisionModelSource.FALLBACK
    assert decision.fallback_reason == JevFailureReason.CALIBRATION_REJECTED.value


def test_jev_clarification_action_uses_deterministic_question_text() -> None:
    class Transport:
        def request_envelope(self, request: JevRequestEnvelope) -> object:
            assert request.definition_id == "next-action.v1"
            return JevResponseEnvelope(
                payload={
                    "decision": {
                        "action": "ask_clarification",
                        "question": None,
                        "options": [],
                        "reason": "model selected clarification",
                    },
                    "source": "jev",
                    "confidence": "high",
                },
                identity=ModelIdentity(
                    model_version="jev-1.13.0",
                    artifact_id="next-action.v1@next-action-definition.v2",
                ),
            )

    registry = QuestionRegistry.from_file(
        Path(__file__).resolve().parents[2]
        / "config"
        / "jev"
        / "question-definitions.v1.yaml"
    )
    adapter = JevDecisionModelAdapter(
        Transport(), RuleBasedDecisionModel(), registry=registry
    )

    result = adapter.choose_next_action(
        _query_session(NextAction.ASK_FOR_EXAMS, ConversationIntent.ADMISSION_SEARCH)
    )

    assert result.source is DecisionModelSource.JEV
    assert result.model_version == "jev-1.13.0"
    assert result.decision.action is DecisionAction.ASK_CLARIFICATION
    assert result.decision.question == "Какие у вас баллы по предметам ЕГЭ?"
    assert result.decision.options


def test_jev_impossible_action_falls_back_to_deterministic_policy() -> None:
    class Transport:
        def request_envelope(self, request: JevRequestEnvelope) -> object:
            return {
                "decision": {
                    "action": "open_mini_app",
                    "question": None,
                    "options": [],
                    "reason": "model selected unsupported action",
                },
                "source": "jev",
                "confidence": "high",
                "model_version": "jev-live-test",
            }

    registry = QuestionRegistry.from_file(
        Path(__file__).resolve().parents[2]
        / "config"
        / "jev"
        / "question-definitions.v1.yaml"
    )
    adapter = JevDecisionModelAdapter(
        Transport(), RuleBasedDecisionModel(), registry=registry
    )

    result = adapter.choose_next_action(
        _query_session(NextAction.EXECUTE_QUERY, ConversationIntent.COMPARE_PROGRAMS)
    )

    assert result.source is DecisionModelSource.FALLBACK
    assert result.fallback_reason == "action_not_applicable"
    assert result.decision.action is DecisionAction.COMPARE


def _query_session(next_action: NextAction, intent: ConversationIntent) -> QuerySession:
    timestamp = datetime(2026, 9, 23, tzinfo=UTC)
    digest = hashlib.sha256(b"jev-adapter-policy-test").hexdigest()
    return QuerySession(
        session_id=f"query-session:{digest[:32]}",
        owner_scope=ProfileScope(session_key_hash=digest),
        intent=intent,
        next_action=next_action,
        missing_slots=(ConversationSlot.EXAMS,)
        if next_action is NextAction.ASK_FOR_EXAMS
        else (),
        revision=1,
        created_at=timestamp,
        updated_at=timestamp,
        expires_at=timestamp + timedelta(hours=1),
    )


def test_olympiad_resolution_fails_closed_without_calibration() -> None:
    class Transport:
        calls = 0

        def request_envelope(self, request: JevRequestEnvelope) -> JevResponseEnvelope:
            self.calls += 1
            raise AssertionError(
                "uncalibrated candidate selection must not call the provider"
            )

    transport = Transport()
    registry = QuestionRegistry.from_file(
        Path(__file__).resolve().parents[2]
        / "config"
        / "jev"
        / "question-definitions.admission.v1.yaml"
    )
    adapter = JevDecisionModelAdapter(
        transport, RuleBasedDecisionModel(), registry=registry
    )

    decision = adapter.resolve_olympiad_profile(
        "Шаг в будущее, Инженерное дело",
        candidates=(
            CandidateResolutionOption(
                candidate_id="olympiad-profile:shag-engineering",
                label="Шаг в будущее — Инженерное дело",
            ),
            CandidateResolutionOption(
                candidate_id="olympiad-profile:shag-programming",
                label="Шаг в будущее — Программирование",
            ),
        ),
    )

    assert decision.candidate_id is None
    assert decision.source is DecisionModelSource.FALLBACK
    assert decision.fallback_reason == "calibration_unavailable"
    assert transport.calls == 0


def test_olympiad_resolution_accepts_only_calibrated_candidate_from_allowlist() -> None:
    class Transport:
        def __init__(self) -> None:
            self.requests: list[JevRequestEnvelope] = []

        def request_envelope(self, request: JevRequestEnvelope) -> JevResponseEnvelope:
            self.requests.append(request)
            return JevResponseEnvelope(
                payload={"candidate_id": "olympiad-profile:shag-engineering"},
                identity=ModelIdentity(
                    provider="typesafe",
                    model="jev",
                    model_version="jev-1.13.0",
                    source=DecisionModelSource.JEV,
                    artifact_id="olympiad-profile-resolution.v1@v1",
                ),
                usage=JevUsage(),
                evidence=JevAnswerEvidence(
                    answer_kind="choice",
                    answer_value="olympiad-profile:shag-engineering",
                    probabilities={
                        "olympiad-profile:shag-engineering": 0.95,
                        "olympiad-profile:shag-programming": 0.05,
                    },
                    has_probability_evidence=True,
                ),
            )

    transport = Transport()
    registry = QuestionRegistry.from_file(
        Path(__file__).resolve().parents[2]
        / "config"
        / "jev"
        / "question-definitions.admission.v1.yaml"
    )
    adapter = JevDecisionModelAdapter(
        transport,
        RuleBasedDecisionModel(),
        registry=registry,
        calibration=_AcceptedCandidateCalibration(),
    )

    decision = adapter.resolve_olympiad_profile(
        "Я призёр олимпиады Шаг в будущее по профилю Инженерное дело, мой телефон +7 999 123-45-67",
        candidates=(
            CandidateResolutionOption(
                candidate_id="olympiad-profile:shag-engineering",
                label="Шаг в будущее — Инженерное дело",
            ),
            CandidateResolutionOption(
                candidate_id="olympiad-profile:shag-programming",
                label="Шаг в будущее — Программирование",
            ),
        ),
    )

    assert decision.candidate_id == "olympiad-profile:shag-engineering"
    assert decision.source is DecisionModelSource.JEV
    assert decision.model_version == "jev-1.13.0"
    payload = transport.requests[0].redacted_payload
    assert "телефон" not in str(payload).casefold()
    assert "+7" not in str(payload)
    assert "999" not in str(payload)
    assert "123-45-67" not in str(payload)


def test_olympiad_resolution_rejects_provider_candidate_outside_allowlist() -> None:
    class Transport:
        def request_envelope(self, request: JevRequestEnvelope) -> JevResponseEnvelope:
            del request
            return JevResponseEnvelope(
                payload={"candidate_id": "olympiad-profile:not-supplied"},
                identity=ModelIdentity(
                    model_version="jev-1.13.0",
                    artifact_id="olympiad-profile-resolution.v1@v1",
                ),
                evidence=JevAnswerEvidence(
                    answer_kind="choice",
                    answer_value="olympiad-profile:not-supplied",
                    probabilities={"olympiad-profile:not-supplied": 1.0},
                    has_probability_evidence=True,
                ),
            )

    class AcceptAllCalibration:
        artifact_id = "fixture-accepted-artifact"

        def evaluate(self, definition_id, evidence, *, model_version=None):
            del definition_id, evidence, model_version
            return type(
                "Gate",
                (),
                {
                    "accepted": True,
                    "artifact_id": self.artifact_id,
                    "reason": "accepted",
                },
            )()

    registry = QuestionRegistry.from_file(
        Path(__file__).resolve().parents[2]
        / "config"
        / "jev"
        / "question-definitions.admission.v1.yaml"
    )
    adapter = JevDecisionModelAdapter(
        Transport(),
        RuleBasedDecisionModel(),
        registry=registry,
        calibration=AcceptAllCalibration(),
    )

    decision = adapter.resolve_olympiad_profile(
        "Шаг в будущее — инженерное дело",
        candidates=(
            CandidateResolutionOption(
                candidate_id="olympiad-profile:shag-engineering",
                label="Шаг в будущее — Инженерное дело",
            ),
            CandidateResolutionOption(
                candidate_id="olympiad-profile:shag-programming",
                label="Шаг в будущее — Программирование",
            ),
        ),
    )

    assert decision.candidate_id is None
    assert decision.source is DecisionModelSource.FALLBACK
    assert decision.fallback_reason == "invalid_provider_output"
