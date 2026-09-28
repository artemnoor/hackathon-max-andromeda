from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import ProfileScope, UserProfile, UserProfileSnapshot
from andromeda.modules.proftest.services.profile_persistence import UserProfilePersistenceService
from andromeda.shared.contracts.errors import NotFoundError


class _Repository:
    def __init__(self) -> None:
        self.snapshot: UserProfileSnapshot | None = None
        self.calls: list[str] = []

    def get_current(self, scope: ProfileScope) -> UserProfileSnapshot | None:
        del scope
        self.calls.append("get")
        return self.snapshot

    def create(self, scope: ProfileScope, profile: UserProfile, *, expires_at: datetime) -> UserProfileSnapshot:
        del scope
        self.calls.append("create")
        self.snapshot = _snapshot(profile, 1, expires_at)
        return self.snapshot

    def update(self, scope: ProfileScope, profile: UserProfile, *, expected_revision: int, expires_at: datetime) -> UserProfileSnapshot:
        del scope, expected_revision
        self.calls.append("update")
        self.snapshot = _snapshot(profile, 2, expires_at)
        return self.snapshot

    def save_current(self, scope: ProfileScope, profile: UserProfile, *, expires_at: datetime) -> UserProfileSnapshot:
        del scope
        self.calls.append("save")
        revision = 1 if self.snapshot is None else self.snapshot.revision + 1
        self.snapshot = _snapshot(profile, revision, expires_at)
        return self.snapshot


def _profile() -> UserProfile:
    return UserProfile(
        interests=(DisciplineAreaCode.MATHEMATICS_STATISTICS,),
        preferred_subject_weights={DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("1")},
    )


def _snapshot(profile: UserProfile, revision: int, expires_at: datetime) -> UserProfileSnapshot:
    now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    return UserProfileSnapshot(
        profile_id="profile:" + "a" * 32,
        profile=profile,
        revision=revision,
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
    )


def test_service_translates_missing_current_profile_and_uses_configured_ttl() -> None:
    repository = _Repository()
    service = UserProfilePersistenceService(
        repository,  # type: ignore[arg-type]
        ttl_seconds=3600,
        clock=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(NotFoundError):
        service.get_current(ProfileScope(session_key_hash="a" * 64))
    created = service.create(ProfileScope(session_key_hash="a" * 64), _profile())

    assert created.revision == 1
    assert created.expires_at == datetime(2027, 1, 1, 1, tzinfo=timezone.utc)
    assert repository.calls == ["get", "create"]


def test_service_save_completed_is_idempotent_by_revision_progression() -> None:
    repository = _Repository()
    service = UserProfilePersistenceService(
        repository,  # type: ignore[arg-type]
        ttl_seconds=60,
        clock=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    scope = ProfileScope(session_key_hash="b" * 64)

    first = service.save_completed(scope, _profile())
    second = service.save_completed(scope, _profile())

    assert first.revision == 1
    assert second.revision == 2
    assert repository.calls == ["save", "save"]
