from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from andromeda.modules.auth.repository.ports import PasswordHasher as PasswordHasherPort


class Argon2PasswordHasher(PasswordHasherPort):
    """Argon2id password hashing with explicit production parameters."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=4)

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError, ValueError):
            return False


__all__ = ["Argon2PasswordHasher"]
