from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.database.models import AccountModel, UniversityModel
from andromeda.infrastructure.repositories.university_admin import SqlAlchemyUniversityAdminMembershipRepository
from andromeda.modules.university_admin.contracts.public import UniversityAdminRole
from andromeda.shared.contracts.errors import ConflictError, NotFoundError


ACCOUNT_ID = "account:" + "a" * 32
OTHER_ACCOUNT_ID = "account:" + "b" * 32
UNIVERSITY_ID = "university:bmstu"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _engine(tmp_path: Path):
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'university-admin.db').as_posix()}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        session.add_all(
            [
                AccountModel(
                    account_id=ACCOUNT_ID,
                    email="owner@example.test",
                    password_hash="hash",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                AccountModel(
                    account_id=OTHER_ACCOUNT_ID,
                    email="editor@example.test",
                    password_hash="hash",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                UniversityModel(
                    id=UNIVERSITY_ID,
                    name="МГТУ им. Н. Э. Баумана",
                    city="Москва",
                    official_site="https://bmstu.ru/",
                    address="Москва",
                ),
            ]
        )
        session.commit()
    return engine


def test_membership_repository_upserts_reactivates_and_lists(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            repository = SqlAlchemyUniversityAdminMembershipRepository(session)
            created = repository.upsert(
                membership_id="membership:" + "c" * 32,
                account_id=ACCOUNT_ID,
                university_id=UNIVERSITY_ID,
                role=UniversityAdminRole.OWNER,
                granted_by_account_id=None,
                now=NOW,
            )
            assert created.role is UniversityAdminRole.OWNER
            assert created.status.value == "active"

            revoked = repository.revoke(
                membership_id=created.membership_id,
                expected_revision=created.revision,
                now=NOW,
            )
            assert revoked.status.value == "revoked"
            assert revoked.revision == 2

            reactivated = repository.upsert(
                membership_id=created.membership_id,
                account_id=ACCOUNT_ID,
                university_id=UNIVERSITY_ID,
                role=UniversityAdminRole.EDITOR,
                granted_by_account_id=OTHER_ACCOUNT_ID,
                now=NOW,
            )
            assert reactivated.status.value == "active"
            assert reactivated.role is UniversityAdminRole.EDITOR
            assert reactivated.revision == 3
            assert repository.list_memberships(ACCOUNT_ID) == (reactivated,)
    finally:
        engine.dispose()


def test_membership_repository_rejects_stale_revoke_and_missing_membership(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            repository = SqlAlchemyUniversityAdminMembershipRepository(session)
            membership = repository.upsert(
                membership_id="membership:" + "d" * 32,
                account_id=ACCOUNT_ID,
                university_id=UNIVERSITY_ID,
                role=UniversityAdminRole.OWNER,
                granted_by_account_id=None,
                now=NOW,
            )
            with pytest.raises(ConflictError):
                repository.revoke(
                    membership_id=membership.membership_id,
                    expected_revision=membership.revision + 1,
                    now=NOW,
                )
            with pytest.raises(NotFoundError):
                repository.revoke(
                    membership_id="membership:" + "e" * 32,
                    expected_revision=1,
                    now=NOW,
                )
    finally:
        engine.dispose()
