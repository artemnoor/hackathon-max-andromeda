import hashlib
import logging
from datetime import UTC, datetime, timedelta

from andromeda.modules.conversation.contracts.policy import (
    DecisionAction,
    DecisionPolicyResult,
    NextActionDecision,
)
from andromeda.modules.conversation.contracts.public import QuerySession
from andromeda.modules.conversation.services.model_decision_policy import (
    ModelBackedDecisionPolicy,
    ShadowDecisionPolicy,
)
from andromeda.modules.conversation.services.rule_decision_policy import (
    RuleBasedDecisionPolicy,
)
from andromeda.modules.proftest.contracts.public import ProfileScope


class _Model:
    def __init__(self, decision: DecisionPolicyResult | None = None) -> None:
        self.calls = 0
        self._decision = decision or DecisionPolicyResult(
            action=DecisionAction.EXECUTE_QUERY,
            reason="model fixture",
        )

    def choose_next_action(self, session, **kwargs):  # type: ignore[no-untyped-def]
        del session, kwargs
        self.calls += 1
        return NextActionDecision(decision=self._decision)


class _FailingModel:
    def choose_next_action(self, session, **kwargs):  # type: ignore[no-untyped-def]
        del session, kwargs
        raise TimeoutError("synthetic provider failure; must not enter telemetry")


def _session() -> QuerySession:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    return QuerySession(
        session_id="query-session:" + "a" * 32,
        owner_scope=ProfileScope(session_key_hash="b" * 64),
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
    )


def test_model_backed_policy_uses_typed_model_answer() -> None:
    result = ModelBackedDecisionPolicy(_Model()).decide(_session())

    assert result.action is DecisionAction.EXECUTE_QUERY


def test_shadow_policy_invokes_model_but_returns_exact_deterministic_result() -> None:
    session = _session()
    model = _Model()
    expected = RuleBasedDecisionPolicy().decide(session)

    result = ShadowDecisionPolicy(model).decide(session)

    assert model.calls == 1
    assert result == expected
    assert result.action is DecisionAction.ASK_CLARIFICATION


def test_shadow_policy_telemetry_redacts_query_session_and_profile(caplog) -> None:
    session = _session().model_copy(
        update={"last_question": "private-query-sentinel; applicant-profile-sentinel"}
    )
    model = _Model()
    caplog.set_level(
        logging.INFO, logger="andromeda.modules.conversation.model_decision_policy"
    )

    ShadowDecisionPolicy(model).decide(session)

    expected_session_hash = hashlib.sha256(
        session.session_id.encode("utf-8")
    ).hexdigest()[:16]
    assert model.calls == 1
    assert expected_session_hash in caplog.text
    assert session.session_id not in caplog.text
    assert session.owner_scope.session_key_hash not in caplog.text
    assert "private-query-sentinel" not in caplog.text
    assert "applicant-profile-sentinel" not in caplog.text
    assert "synthetic provider failure" not in caplog.text


def test_shadow_provider_error_preserves_deterministic_decision(caplog) -> None:
    session = _session()
    expected = RuleBasedDecisionPolicy().decide(session)
    caplog.set_level(
        logging.INFO, logger="andromeda.modules.conversation.model_decision_policy"
    )

    result = ShadowDecisionPolicy(_FailingModel()).decide(session)

    assert result == expected
    assert "fallback_reason=TimeoutError" in caplog.text
    assert "synthetic provider failure" not in caplog.text
