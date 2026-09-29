from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import UserProfileModel
from andromeda.infrastructure.repositories.user_profiles import SqlAlchemyUserProfileRepository
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import ActivityCode, ProfileBindingOutcome, ProfileScope, UserProfile
from andromeda.shared.contracts.errors import ConflictError, NotFoundError


def _profile(subject: DisciplineAreaCode = DisciplineAreaCode.COMPUTER_SCIENCE_DATA) -> UserProfile:
    return UserProfile(
        interests=(subject,),
        activity_preferences=(ActivityCode.ANALYTICAL,),
        preferred_subject_weights={subject: Decimal("1")},
        preferred_activity_weights={ActivityCode.ANALYTICAL: Decimal("1")},
    )


def _expires(days: int = 30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def test_repository_round_trips_profile_and_supports_optimistic_update(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'profiles.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="a" * 64)

    with Session(engine) as session:
        repository = SqlAlchemyUserProfileRepository(session)
        created = repository.create(scope, _profile(), expires_at=_expires())
        read = repository.get_current(scope)
        updated = repository.update(
            scope,
            _profile(DisciplineAreaCode.MATHEMATICS_STATISTICS),
            expected_revision=created.revision,
            expires_at=_expires(),
        )

    assert read is not None
    assert read.profile.preferred_subject_weights[DisciplineAreaCode.COMPUTER_SCIENCE_DATA] == Decimal("1")
    assert updated.profile_id == created.profile_id
    assert updated.revision == 2
    assert updated.profile.interests == (DisciplineAreaCode.MATHEMATICS_STATISTICS,)


def test_repository_rejects_duplicate_and_stale_writes(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'conflicts.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="b" * 64)

    with Session(engine) as session:
        repository = SqlAlchemyUserProfileRepository(session)
        created = repository.create(scope, _profile(), expires_at=_expires())
        with pytest.raises(ConflictError):
            repository.create(scope, _profile(), expires_at=_expires())
        with pytest.raises(ConflictError):
            repository.update(scope, _profile(), expected_revision=created.revision - 1, expires_at=_expires())


def test_expired_row_is_absent_and_completed_save_replaces_it(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'expired.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="c" * 64)
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with Session(engine) as session:
        session.add(
            UserProfileModel(
                profile_id="profile:" + "d" * 32,
                session_key_hash=scope.session_key_hash,
                profile_json=_profile().model_dump(mode="json"),
                revision=4,
                created_at=expired_at - timedelta(days=1),
                updated_at=expired_at - timedelta(days=1),
                expires_at=expired_at,
            )
        )
        session.commit()
        repository = SqlAlchemyUserProfileRepository(session)

        assert repository.get_current(scope) is None
        saved = repository.save_current(scope, _profile(), expires_at=_expires())

    assert saved.revision == 1
    assert saved.profile_id != "profile:" + "d" * 32


def test_update_missing_profile_raises_not_found(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'missing.db').as_posix()}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        with pytest.raises(NotFoundError):
            SqlAlchemyUserProfileRepository(session).update(
                ProfileScope(session_key_hash="e" * 64), _profile(), expected_revision=1, expires_at=_expires()
            )


def test_binding_clears_anonymous_owner_and_restores_by_account(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'binding.db').as_posix()}")
    Base.metadata.create_all(engine)
    anonymous_scope = ProfileScope(session_key_hash="f" * 64)
    account_id = "account:" + "1" * 32
    account_scope = ProfileScope(session_key_hash="f" * 64, account_id=account_id)

    with Session(engine) as session:
        repository = SqlAlchemyUserProfileRepository(session)
        repository.create(anonymous_scope, _profile(), expires_at=_expires())
        assert repository.bind_anonymous_to_account(anonymous_scope, account_id) is ProfileBindingOutcome.BOUND
        assert repository.get_current(anonymous_scope) is None
        restored = repository.get_current(account_scope)

    assert restored is not None


def test_account_profile_wins_without_merging_anonymous_row(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'binding-conflict.db').as_posix()}")
    Base.metadata.create_all(engine)
    account_id = "account:" + "2" * 32
    account_scope = ProfileScope(session_key_hash="1" * 64, account_id=account_id)
    anonymous_scope = ProfileScope(session_key_hash="2" * 64)

    with Session(engine) as session:
        repository = SqlAlchemyUserProfileRepository(session)
        account_profile = repository.create(account_scope, _profile(DisciplineAreaCode.MATHEMATICS_STATISTICS), expires_at=_expires())
        repository.create(anonymous_scope, _profile(), expires_at=_expires())
        assert repository.bind_anonymous_to_account(anonymous_scope, account_id) is ProfileBindingOutcome.ACCOUNT_PROFILE_KEPT
        assert repository.get_current(account_scope).profile.interests == account_profile.profile.interests  # type: ignore[union-attr]
        assert repository.get_current(anonymous_scope) is not None
