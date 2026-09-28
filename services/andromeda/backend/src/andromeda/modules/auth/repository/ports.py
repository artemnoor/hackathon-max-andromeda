from __future__ import annotations

from datetime import datetime
from typing import Protocol

from andromeda.modules.proftest.repository.ports import ProfileBindingPort
from andromeda.shared.contracts.ids import AccountId, SessionTokenHash

from ..domain.entities import Account


class AccountRepository(Protocol):
    def get_by_email(self, email: str) -> Account | None: ...

    def get_credentials(self, email: str) -> tuple[Account, str] | None: ...

    def get_by_id(self, account_id: AccountId) -> Account | None: ...

    def create(self, account_id: AccountId, email: str, password_hash: str, *, now: datetime) -> Account: ...

    def create_session(self, account_id: AccountId, token_hash: SessionTokenHash, *, now: datetime, expires_at: datetime) -> None: ...

    def get_by_session_hash(self, token_hash: SessionTokenHash, *, now: datetime) -> Account | None: ...

    def purge_expired_sessions(self, *, now: datetime) -> int: ...

    def revoke_session(self, token_hash: SessionTokenHash, *, now: datetime) -> None: ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...


__all__ = ["AccountRepository", "PasswordHasher", "ProfileBindingPort"]
