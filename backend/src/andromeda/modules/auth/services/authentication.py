from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re
from collections.abc import Callable
from uuid import uuid4

from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.proftest.repository.ports import ProfileBindingPort, ProftestSessionBindingPort
from andromeda.modules.decision.repository.ports import DecisionBindingOutcome, DecisionBindingPort
from andromeda.shared.contracts.errors import ConflictError, UnauthorizedError, ValidationError
from andromeda.shared.contracts.ids import AccountId, SessionTokenHash

from ..domain.entities import Account, AuthSessionResult
from ..repository.ports import AccountRepository, PasswordHasher


logger = logging.getLogger("andromeda.auth.service")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthenticationService:
    """Account/session use cases expressed only through typed ports."""

    def __init__(
        self,
        repository: AccountRepository,
        password_hasher: PasswordHasher,
        profile_binding: ProfileBindingPort,
        session_binding: ProftestSessionBindingPort | None = None,
        decision_binding: DecisionBindingPort | None = None,
        *,
        password_min_length: int = 12,
        session_ttl_seconds: int = 60 * 60 * 24 * 30,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repository = repository
        self._password_hasher = password_hasher
        self._profile_binding = profile_binding
        self._session_binding = session_binding
        self._decision_binding = decision_binding
        self._password_min_length = password_min_length
        self._session_ttl_seconds = session_ttl_seconds
        self._clock = clock
        self._last_decision_binding: DecisionBindingOutcome | None = None

    @property
    def last_decision_binding(self) -> DecisionBindingOutcome | None:
        """Outcome for the current auth request, for an explicit UI notice."""

        return self._last_decision_binding

    def register(self, email: str, password: str, token_hash: SessionTokenHash, profile_scope: ProfileScope) -> Account:
        normalized_email = _normalize_email(email)
        self._validate_password(password)
        now = self._clock()
        account_id = _account_id()
        password_hash = self._password_hasher.hash(password)
        logger.debug("auth_register_start account_id=%s", account_id)
        self._repository.purge_expired_sessions(now=now)
        try:
            account = self._repository.create(account_id, normalized_email, password_hash, now=now)
        except ConflictError:
            logger.info("auth_register_rejected outcome=duplicate")
            raise
        self._repository.create_session(account.account_id, token_hash, now=now, expires_at=self._expires_at(now))
        self._bind_profile(account, profile_scope)
        logger.info("auth_register_complete account_id=%s profile_binding=attempted", account.account_id)
        return account

    def login(self, email: str, password: str, token_hash: SessionTokenHash, profile_scope: ProfileScope) -> Account:
        normalized_email = _normalize_email(email)
        credentials = self._repository.get_credentials(normalized_email)
        if credentials is None or not self._password_hasher.verify(credentials[1], password):
            logger.warning("auth_login_rejected outcome=invalid_credentials")
            raise UnauthorizedError("Invalid email or password")
        account = credentials[0]
        now = self._clock()
        self._repository.purge_expired_sessions(now=now)
        self._repository.create_session(account.account_id, token_hash, now=now, expires_at=self._expires_at(now))
        self._bind_profile(account, profile_scope)
        logger.info("auth_login_complete account_id=%s profile_binding=attempted", account.account_id)
        return account

    def current(self, token_hash: SessionTokenHash | None) -> AuthSessionResult:
        if token_hash is None:
            return AuthSessionResult(authenticated=False, account=None)
        account = self._repository.get_by_session_hash(token_hash, now=self._clock())
        return AuthSessionResult(authenticated=account is not None, account=account)

    def logout(self, token_hash: SessionTokenHash | None) -> None:
        if token_hash is None:
            return
        self._repository.revoke_session(token_hash, now=self._clock())
        logger.info("auth_logout_complete outcome=revoked")

    def import_guest_decision(self, account: Account, profile_scope: ProfileScope) -> DecisionBindingOutcome:
        if self._decision_binding is None:
            raise ConflictError("Decision context binding is unavailable")
        outcome = self._decision_binding.replace_account_with_anonymous(profile_scope, account.account_id)
        self._last_decision_binding = outcome
        logger.info("auth_decision_import_complete account_id=%s outcome=%s", account.account_id, outcome.value)
        return outcome

    def _bind_profile(self, account: Account, profile_scope: ProfileScope) -> None:
        outcome = self._profile_binding.bind_anonymous_to_account(profile_scope, account.account_id)
        logger.info("auth_profile_binding_complete account_id=%s outcome=%s", account.account_id, outcome.value)
        if self._session_binding is not None:
            session_outcome = self._session_binding.bind_anonymous_session_to_account(profile_scope, account.account_id)
            logger.info("auth_session_binding_complete account_id=%s outcome=%s", account.account_id, session_outcome.value)
        if self._decision_binding is not None:
            decision_outcome = self._decision_binding.bind_anonymous_to_account(profile_scope, account.account_id)
            self._last_decision_binding = decision_outcome
            logger.info("auth_decision_binding_complete account_id=%s outcome=%s", account.account_id, decision_outcome.value)

    def _validate_password(self, password: str) -> None:
        if len(password) < self._password_min_length:
            raise ValidationError(f"Password must contain at least {self._password_min_length} characters")

    def _expires_at(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self._session_ttl_seconds)


def _normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if _EMAIL_PATTERN.fullmatch(normalized) is None or len(normalized) > 320:
        raise ValidationError("Email address is invalid")
    return normalized


def _account_id() -> AccountId:
    return f"account:{uuid4().hex}"


__all__ = ["AuthenticationService"]
