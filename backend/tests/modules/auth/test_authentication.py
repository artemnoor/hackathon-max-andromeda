from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from andromeda.modules.auth.contracts.public import Account
from andromeda.modules.auth.repository.ports import AccountRepository, PasswordHasher
from andromeda.modules.auth.services.authentication import AuthenticationService
from andromeda.modules.proftest.contracts.public import ProfileBindingOutcome, ProfileScope
from andromeda.shared.contracts.errors import UnauthorizedError
from andromeda.shared.contracts.ids import AccountId, SessionTokenHash


class FakeHasher(PasswordHasher):
    def hash(self, password: str) -> str:
        return "argon2:" + password

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == self.hash(password)


class FakeRepository(AccountRepository):
    def __init__(self) -> None:
        self.accounts: dict[str, tuple[Account, str]] = {}
        self.sessions: dict[str, tuple[AccountId, datetime, bool]] = {}

    def get_by_email(self, email: str) -> Account | None:
        credentials = self.get_credentials(email)
        return credentials[0] if credentials else None

    def get_credentials(self, email: str) -> tuple[Account, str] | None:
        return next((value for value in self.accounts.values() if value[0].email == email), None)

    def get_by_id(self, account_id: AccountId) -> Account | None:
        value = self.accounts.get(account_id)
        return value[0] if value else None

    def create(self, account_id: AccountId, email: str, password_hash: str, *, now: datetime) -> Account:
        if self.get_by_email(email) is not None:
            from andromeda.shared.contracts.errors import ConflictError

            raise ConflictError("Account already exists")
        account = Account(accountId=account_id, email=email, createdAt=now)
        self.accounts[account_id] = (account, password_hash)
        return account

    def create_session(self, account_id: AccountId, token_hash: SessionTokenHash, *, now: datetime, expires_at: datetime) -> None:
        self.sessions[token_hash] = (account_id, expires_at, False)

    def get_by_session_hash(self, token_hash: SessionTokenHash, *, now: datetime) -> Account | None:
        session = self.sessions.get(token_hash)
        if session is None or session[2] or session[1] <= now:
            return None
        return self.get_by_id(session[0])

    def purge_expired_sessions(self, *, now: datetime) -> int:
        expired = [token for token, session in self.sessions.items() if session[1] <= now]
        for token in expired:
            del self.sessions[token]
        return len(expired)

    def revoke_session(self, token_hash: SessionTokenHash, *, now: datetime) -> None:
        session = self.sessions.get(token_hash)
        if session:
            self.sessions[token_hash] = (session[0], session[1], True)


class FakeBinding:
    def __init__(self) -> None:
        self.calls: list[AccountId] = []

    def bind_anonymous_to_account(self, scope: ProfileScope, account_id: AccountId) -> ProfileBindingOutcome:
        self.calls.append(account_id)
        return ProfileBindingOutcome.BOUND


def _service() -> tuple[AuthenticationService, FakeRepository, FakeBinding]:
    repository = FakeRepository()
    binding = FakeBinding()
    now = datetime.now(timezone.utc)
    return AuthenticationService(repository, FakeHasher(), binding, clock=lambda: now), repository, binding


def test_registration_normalizes_email_and_binds_profile() -> None:
    service, repository, binding = _service()
    account = service.register(" STUDENT@EXAMPLE.COM ", "a-secure-password", "a" * 64, ProfileScope(session_key_hash="b" * 64))
    assert account.email == "student@example.com"
    assert repository.get_credentials("student@example.com") is not None
    assert binding.calls == [account.account_id]


def test_login_uses_generic_error_and_sessions_are_revocable() -> None:
    service, _, _ = _service()
    service.register("student@example.com", "a-secure-password", "a" * 64, ProfileScope(session_key_hash="b" * 64))
    with pytest.raises(UnauthorizedError, match="Invalid email or password"):
        service.login("unknown@example.com", "wrong-password", "c" * 64, ProfileScope(session_key_hash="d" * 64))
    account = service.login("student@example.com", "a-secure-password", "c" * 64, ProfileScope(session_key_hash="d" * 64))
    assert service.current("c" * 64).account == account
    service.logout("c" * 64)
    assert service.current("c" * 64).authenticated is False


def test_short_registration_password_is_rejected() -> None:
    service, _, _ = _service()
    with pytest.raises(Exception, match="at least 12"):
        service.register("student@example.com", "short", "a" * 64, ProfileScope(session_key_hash="b" * 64))
