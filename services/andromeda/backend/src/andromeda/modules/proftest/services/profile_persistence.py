"""Application use cases for the current UserProfile snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging

from andromeda.shared.contracts.errors import NotFoundError, ValidationError
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode

from ..contracts.public import ActivityCode, ProfileRefinement, ProfileScope, UserProfile, UserProfileSnapshot
from ..domain.profiling import normalize_weights
from ..domain.values import ZERO, quantize_ratio
from ..repository.ports import UserProfileRepository


logger = logging.getLogger("andromeda.proftest.profile_persistence")


class UserProfilePersistenceService:
    """Coordinate profile use cases without knowing HTTP or storage details."""

    def __init__(self, repository: UserProfileRepository, *, ttl_seconds: int, clock: Callable[[], datetime] | None = None) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self._repository = repository
        self._ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_current(self, scope: ProfileScope) -> UserProfileSnapshot:
        logger.debug("profile_persistence_start operation=get_current")
        snapshot = self._repository.get_current(scope)
        if snapshot is None:
            logger.warning("profile_persistence_empty operation=get_current outcome=not_found")
            raise NotFoundError("Current profile was not found")
        logger.info("profile_persistence_complete operation=get_current revision=%d", snapshot.revision)
        return snapshot

    def create(self, scope: ProfileScope, profile: UserProfile) -> UserProfileSnapshot:
        logger.debug("profile_persistence_start operation=create profile_axis_count=%d", _axis_count(profile))
        snapshot = self._repository.create(scope, profile, expires_at=self._expires_at())
        logger.info("profile_persistence_complete operation=create revision=%d", snapshot.revision)
        return snapshot

    def update(self, scope: ProfileScope, profile: UserProfile, *, expected_revision: int) -> UserProfileSnapshot:
        if expected_revision < 1:
            raise ValidationError("expected_revision must be positive")
        logger.debug("profile_persistence_start operation=update expected_revision=%d profile_axis_count=%d", expected_revision, _axis_count(profile))
        snapshot = self._repository.update(
            scope,
            profile,
            expected_revision=expected_revision,
            expires_at=self._expires_at(),
        )
        logger.info("profile_persistence_complete operation=update revision=%d", snapshot.revision)
        return snapshot

    def save_completed(self, scope: ProfileScope, profile: UserProfile) -> UserProfileSnapshot:
        """Persist a completed test, creating or advancing the current revision."""

        logger.debug("profile_persistence_start operation=save_completed profile_axis_count=%d", _axis_count(profile))
        snapshot = self._repository.save_current(scope, profile, expires_at=self._expires_at())
        logger.info("profile_persistence_complete operation=save_completed revision=%d", snapshot.revision)
        return snapshot

    def apply_refinement(
        self,
        scope: ProfileScope,
        refinement: ProfileRefinement,
        *,
        expected_revision: int,
    ) -> UserProfileSnapshot:
        """Persist one deterministic candidate-preference refinement.

        Subject/activity dimensions affect Content Fit immediately.  A
        distinctive-content dimension is retained as a bounded context marker
        because it has no independent scoring axis in the public profile
        contract; it is never silently translated into an invented area.
        """

        current = self._repository.get_current(scope)
        if current is None:
            raise NotFoundError("Current profile was not found")
        if current.revision != expected_revision:
            from andromeda.shared.contracts.errors import ConflictError

            raise ConflictError("Current profile revision is stale")

        profile = current.profile
        subject_weights = dict(profile.preferred_subject_weights)
        activity_weights = dict(profile.preferred_activity_weights)
        context = set(profile.decision_context)
        confidence = dict(profile.confidence_by_dimension)
        kind, _, value = refinement.affected_dimension.partition(":")
        if kind == "subject":
            try:
                area = DisciplineAreaCode(value)
            except ValueError as exc:
                raise ValidationError("Refinement subject dimension is not supported") from exc
            subject_weights[area] = subject_weights.get(area, ZERO) + quantize_ratio(Decimal("0.35"))
        elif kind == "activity":
            try:
                activity = ActivityCode(value)
            except ValueError as exc:
                raise ValidationError("Refinement activity dimension is not supported") from exc
            activity_weights[activity] = activity_weights.get(activity, ZERO) + quantize_ratio(Decimal("0.35"))
        elif kind == "content" and value:
            context.add(f"refinement_content:{value[:96]}")
        else:
            raise ValidationError("Refinement dimension is not supported")

        confidence[refinement.affected_dimension] = quantize_ratio(Decimal("1"))
        updated = profile.model_copy(
            update={
                "preferred_subject_weights": normalize_weights(subject_weights),
                "preferred_activity_weights": normalize_weights(activity_weights),
                "decision_context": tuple(sorted(context))[:12],
                "confidence_by_dimension": confidence,
            }
        )
        logger.info(
            "profile_refinement_complete dimension=%s revision=%d",
            _safe_dimension(refinement.affected_dimension),
            expected_revision + 1,
        )
        return self.update(scope, updated, expected_revision=expected_revision)

    def _expires_at(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValidationError("profile persistence clock must be timezone-aware")
        return now + timedelta(seconds=self._ttl_seconds)


def _axis_count(profile: UserProfile) -> int:
    return len(profile.preferred_subject_weights) + len(profile.preferred_activity_weights) + len(profile.negative_weights)


def _safe_dimension(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")[:128]


__all__ = ["UserProfilePersistenceService"]
