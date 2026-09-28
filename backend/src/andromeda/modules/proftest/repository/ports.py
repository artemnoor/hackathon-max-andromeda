"""Ports consumed by proftest application services."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from andromeda.modules.curricula.contracts.public import Curriculum
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.ids import AccountId, DisciplineId, ProgramId

from ..domain.entities import UserProfile
from ..domain.profile import ProfileRefinement, ProfileScope, UserProfileSnapshot
from ..domain.sessions import ProftestAnalyticsEvent, ProftestAnswerSession


class ProftestCatalogReader(Protocol):
    """Read canonical content without exposing storage or transport details."""

    def list_programs(self) -> tuple[Program, ...]: ...

    def get_curriculum(self, program_id: ProgramId) -> Curriculum | None: ...

    def get_discipline(self, discipline_id: DisciplineId) -> Discipline | None: ...


class ProftestCatalogSnapshot:
    """One catalog row prepared for fingerprint construction."""

    def __init__(
        self,
        program: Program,
        curriculum: Curriculum | None,
        disciplines: Mapping[DisciplineId, Discipline],
    ) -> None:
        self.program = program
        self.curriculum = curriculum
        self.disciplines = disciplines


@runtime_checkable
class BulkProftestCatalogReader(Protocol):
    """Optional optimized read port for a complete canonical catalog snapshot."""

    def list_catalog_snapshots(self) -> tuple[ProftestCatalogSnapshot, ...]: ...


class CurrentUserProfileReader(Protocol):
    """Read the current profile without exposing its storage implementation."""

    def get_current(self, scope: ProfileScope) -> UserProfileSnapshot | None: ...


class UserProfileRefinementWriter(Protocol):
    """Apply one validated preference signal without owning decision state."""

    def apply_refinement(
        self,
        scope: ProfileScope,
        refinement: ProfileRefinement,
        *,
        expected_revision: int,
    ) -> UserProfileSnapshot: ...


class UserProfileRepository(CurrentUserProfileReader, Protocol):
    """Persistence port for anonymous/session-owned profiles."""

    def create(self, scope: ProfileScope, profile: UserProfile, *, expires_at: datetime) -> UserProfileSnapshot: ...

    def update(
        self,
        scope: ProfileScope,
        profile: UserProfile,
        *,
        expected_revision: int,
        expires_at: datetime,
    ) -> UserProfileSnapshot: ...

    def save_current(self, scope: ProfileScope, profile: UserProfile, *, expires_at: datetime) -> UserProfileSnapshot: ...


class ProfileBindingPort(Protocol):
    """Transfer an anonymous profile to one account without field-level merge."""

    def bind_anonymous_to_account(self, scope: ProfileScope, account_id: AccountId) -> ProfileBindingOutcome: ...


class ProftestSessionBindingPort(Protocol):
    """Transfer one anonymous draft to an account without merging answer fields."""

    def bind_anonymous_session_to_account(self, scope: ProfileScope, account_id: AccountId) -> ProfileBindingOutcome: ...


class ProftestAnswerSessionRepository(Protocol):
    """Persistence boundary for unfinished and completed answer sessions."""

    def get_current(self, scope: ProfileScope) -> ProftestAnswerSession | None: ...

    def start(self, scope: ProfileScope, *, question_set_version: str, current_question_id: str, expires_at: datetime) -> ProftestAnswerSession: ...

    def save(self, scope: ProfileScope, session: ProftestAnswerSession, *, expected_revision: int) -> ProftestAnswerSession: ...

    def complete(self, scope: ProfileScope, session: ProftestAnswerSession, profile: UserProfile, *, expires_at: datetime) -> tuple[ProftestAnswerSession, UserProfileSnapshot]: ...


class ProftestAnalyticsWriter(Protocol):
    """Bounded, idempotent analytics write and aggregate read boundary."""

    def append(self, scope: ProfileScope, events: tuple[ProftestAnalyticsEvent, ...]) -> int: ...

    def aggregates(self, *, question_set_version: str) -> dict[str, int | float]: ...


class ProfileBindingOutcome(str, Enum):
    BOUND = "bound"
    ACCOUNT_PROFILE_KEPT = "account_profile_kept"
    NO_ANONYMOUS_PROFILE = "no_anonymous_profile"


__all__ = [
    "BulkProftestCatalogReader",
    "CurrentUserProfileReader",
    "UserProfileRefinementWriter",
    "ProfileBindingOutcome",
    "ProfileBindingPort",
    "ProftestSessionBindingPort",
    "ProftestAnalyticsWriter",
    "ProftestAnswerSessionRepository",
    "ProftestCatalogReader",
    "ProftestCatalogSnapshot",
    "UserProfileRepository",
]
