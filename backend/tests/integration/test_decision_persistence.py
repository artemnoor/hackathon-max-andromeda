from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.decision import SqlAlchemyDecisionContextRepository
from andromeda.modules.decision.domain.values import DecisionSourceKind, ShortlistRole
from andromeda.modules.proftest.contracts.public import ProfileScope


PROGRAM_A = "program:09.03.01-01"


def test_anonymous_context_survives_a_new_session_and_two_scopes_are_isolated(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'decision-reload.db').as_posix()}")
    Base.metadata.create_all(engine)
    first_scope = ProfileScope(session_key_hash="a" * 64)
    other_scope = ProfileScope(session_key_hash="b" * 64)
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    with Session(engine) as session:
        repository = SqlAlchemyDecisionContextRepository(session)
        created = repository.get_or_create(first_scope, expires_at=expires_at)
        state = created.state.with_choice(
            created.state.choice.add_shortlist(
                PROGRAM_A,
                role=ShortlistRole.PRIMARY,
                origin=DecisionSourceKind.USER,
                now=datetime.now(timezone.utc),
            ),
            now=datetime.now(timezone.utc),
        )
        repository.save(first_scope, state, expected_revision=created.revision, expires_at=expires_at)
        repository.get_or_create(other_scope, expires_at=expires_at)

    with Session(engine) as reloaded_session:
        repository = SqlAlchemyDecisionContextRepository(reloaded_session)
        reloaded = repository.get_current(first_scope)
        isolated = repository.get_current(other_scope)

    assert reloaded is not None
    assert tuple(item.program_id for item in reloaded.state.choice.active_shortlist) == (PROGRAM_A,)
    assert isolated is not None
    assert isolated.state.choice.active_shortlist == ()


def test_account_binding_transfers_only_when_account_has_no_current_state(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'decision-account-binding.db').as_posix()}")
    Base.metadata.create_all(engine)
    anonymous_scope = ProfileScope(session_key_hash="c" * 64)
    account_scope = ProfileScope(session_key_hash="c" * 64, account_id="account:" + "3" * 32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    with Session(engine) as session:
        repository = SqlAlchemyDecisionContextRepository(session)
        anonymous = repository.get_or_create(anonymous_scope, expires_at=expires_at)
        assert repository.bind_anonymous_to_account(anonymous_scope, account_scope.account_id).value == "bound"
        assert repository.get_current(account_scope) is not None

        account_context = repository.get_current(account_scope)
        assert account_context is not None
        second_anonymous_scope = ProfileScope(session_key_hash="d" * 64)
        repository.get_or_create(second_anonymous_scope, expires_at=expires_at)
        assert repository.bind_anonymous_to_account(second_anonymous_scope, account_scope.account_id).value == "account_state_kept"
        assert repository.get_current(second_anonymous_scope) is not None
        assert repository.get_current(account_scope).decision_id == account_context.decision_id  # type: ignore[union-attr]

    assert anonymous.decision_id == account_context.decision_id
