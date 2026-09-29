from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import DecisionContextModel
from andromeda.infrastructure.repositories.decision import SqlAlchemyDecisionContextRepository
from andromeda.modules.decision.contracts.public import DecisionContext, DecisionContextMetadata
from andromeda.modules.decision.domain.entities import DecisionChoice, DecisionState
from andromeda.modules.decision.domain.values import DecisionSourceKind, ShortlistRole
from andromeda.modules.decision.repository.ports import DecisionBindingOutcome
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.shared.contracts.errors import ConflictError, ContractError, NotFoundError


PROGRAM_A = "program:09.03.01-01"
PROGRAM_B = "program:09.03.01-02"


def _expires(days: int = 30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _next_state(snapshot, program_id: str = PROGRAM_A) -> DecisionState:
    now = datetime.now(timezone.utc)
    choice = snapshot.state.choice.add_shortlist(
        program_id,
        role=ShortlistRole.PRIMARY,
        origin=DecisionSourceKind.USER,
        now=now,
    )
    return snapshot.state.with_choice(choice, now=now)


def test_repository_round_trips_explicit_state_and_optimistic_revision(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'decision.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="a" * 64)

    with Session(engine) as session:
        repository = SqlAlchemyDecisionContextRepository(session)
        created = repository.get_or_create(scope, expires_at=_expires())
        assert created.revision == 1
        assert created.state.choice.active_shortlist == ()

        saved = repository.save(scope, _next_state(created), expected_revision=created.revision, expires_at=_expires())
        read = repository.get_current(scope)

        assert read is not None
        assert saved.revision == 2
        assert read.state.choice.active_shortlist[0].program_id == PROGRAM_A
        assert "preferences" not in read.state.model_dump()


def test_repository_rejects_stale_and_invalid_revision_writes(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'decision-conflicts.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="b" * 64)

    with Session(engine) as session:
        repository = SqlAlchemyDecisionContextRepository(session)
        created = repository.get_or_create(scope, expires_at=_expires())
        next_state = _next_state(created)
        stale_state = next_state.model_copy(update={"revision": next_state.revision + 1})
        with pytest.raises(ConflictError):
            repository.save(scope, stale_state, expected_revision=created.revision + 1, expires_at=_expires())
        with pytest.raises(ContractError):
            repository.save(scope, next_state, expected_revision=created.revision, expires_at=_expires(days=-1))
        with pytest.raises(NotFoundError):
            repository.save(
                ProfileScope(session_key_hash="1" * 64),
                next_state,
                expected_revision=created.revision,
                expires_at=_expires(),
            )


def test_expired_context_is_absent_and_get_or_create_replaces_it(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'decision-expired.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="c" * 64)
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    with Session(engine) as session:
        session.add(
            DecisionContextModel(
                decision_id="decision:" + "d" * 32,
                owner_key=scope.owner_key,
                session_key_hash=scope.session_key_hash,
                account_id=None,
                state_json=DecisionState(
                    revision=4,
                    created_at=expired_at - timedelta(days=1),
                    updated_at=expired_at - timedelta(days=1),
                ).model_dump(mode="json"),
                revision=4,
                created_at=expired_at - timedelta(days=1),
                updated_at=expired_at - timedelta(days=1),
                expires_at=expired_at,
            )
        )
        session.commit()
        repository = SqlAlchemyDecisionContextRepository(session)
        assert repository.get_current(scope) is None
        replacement = repository.get_or_create(scope, expires_at=_expires())

    assert replacement.revision == 1
    assert replacement.decision_id != "decision:" + "d" * 32


def test_binding_moves_anonymous_context_without_merging_account_state(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'decision-binding.db').as_posix()}")
    Base.metadata.create_all(engine)
    anonymous_scope = ProfileScope(session_key_hash="e" * 64)
    account_id = "account:" + "1" * 32
    account_scope = ProfileScope(session_key_hash="e" * 64, account_id=account_id)

    with Session(engine) as session:
        repository = SqlAlchemyDecisionContextRepository(session)
        anonymous = repository.get_or_create(anonymous_scope, expires_at=_expires())
        repository.save(anonymous_scope, _next_state(anonymous), expected_revision=anonymous.revision, expires_at=_expires())
        assert repository.bind_anonymous_to_account(anonymous_scope, account_id) is DecisionBindingOutcome.BOUND
        assert repository.get_current(anonymous_scope) is None
        restored = repository.get_current(account_scope)

    assert restored is not None
    assert restored.state.choice.active_shortlist[0].program_id == PROGRAM_A


def test_account_state_wins_and_anonymous_state_is_not_deleted(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'decision-binding-conflict.db').as_posix()}")
    Base.metadata.create_all(engine)
    account_id = "account:" + "2" * 32
    account_scope = ProfileScope(session_key_hash="f" * 64, account_id=account_id)
    anonymous_scope = ProfileScope(session_key_hash="0" * 64)

    with Session(engine) as session:
        repository = SqlAlchemyDecisionContextRepository(session)
        account = repository.get_or_create(account_scope, expires_at=_expires())
        repository.save(account_scope, _next_state(account, PROGRAM_B), expected_revision=account.revision, expires_at=_expires())
        anonymous = repository.get_or_create(anonymous_scope, expires_at=_expires())
        repository.save(anonymous_scope, _next_state(anonymous, PROGRAM_A), expected_revision=anonymous.revision, expires_at=_expires())

        assert repository.bind_anonymous_to_account(anonymous_scope, account_id) is DecisionBindingOutcome.ACCOUNT_STATE_KEPT
        kept_account = repository.get_current(account_scope)
        kept_anonymous = repository.get_current(anonymous_scope)

    assert kept_account is not None
    assert kept_anonymous is not None
    assert kept_account.state.choice.active_shortlist[0].program_id == PROGRAM_B
    assert kept_anonymous.state.choice.active_shortlist[0].program_id == PROGRAM_A


def test_explicit_guest_import_replaces_account_state_only_after_command(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'decision-binding-import.db').as_posix()}")
    Base.metadata.create_all(engine)
    account_id = "account:" + "3" * 32
    account_scope = ProfileScope(session_key_hash="1" * 64, account_id=account_id)
    anonymous_scope = ProfileScope(session_key_hash="2" * 64)

    with Session(engine) as session:
        repository = SqlAlchemyDecisionContextRepository(session)
        account = repository.get_or_create(account_scope, expires_at=_expires())
        repository.save(account_scope, _next_state(account, PROGRAM_B), expected_revision=account.revision, expires_at=_expires())
        anonymous = repository.get_or_create(anonymous_scope, expires_at=_expires())
        repository.save(anonymous_scope, _next_state(anonymous, PROGRAM_A), expected_revision=anonymous.revision, expires_at=_expires())

        assert repository.bind_anonymous_to_account(anonymous_scope, account_id) is DecisionBindingOutcome.ACCOUNT_STATE_KEPT
        assert repository.replace_account_with_anonymous(anonymous_scope, account_id) is DecisionBindingOutcome.BOUND
        imported = repository.get_current(account_scope)

    assert imported is not None
    assert imported.state.choice.active_shortlist[0].program_id == PROGRAM_A


def test_storage_state_has_no_hydrated_profile_contract() -> None:
    state = DecisionState()
    context = DecisionContext(
        decision_id="decision:" + "a" * 32,
        state=state,
        metadata=DecisionContextMetadata(
            decision_id="decision:" + "a" * 32,
            revision=state.revision,
            status=state.status,
            created_at=state.created_at,
            updated_at=state.updated_at,
        ),
    )

    assert "preferences" not in state.model_dump()
    assert context.preferences is None
