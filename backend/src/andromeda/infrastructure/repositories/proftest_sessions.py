"""SQLAlchemy adapters for resumable proftest sessions and analytics."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from andromeda.modules.proftest.contracts.public import (
    AnalyticsEventType,
    AdaptiveAnswer,
    AdaptiveState,
    Answer,
    AnswerSet,
    AnswerStatus,
    ProfileBindingOutcome,
    ProfileScope,
    ProftestAnalyticsEvent,
    ProftestAnswerSession,
    Question,
    SessionStatus,
    UserProfile,
    UserProfileSnapshot,
)
from andromeda.modules.proftest.repository.ports import ProftestAnalyticsWriter, ProftestAnswerSessionRepository, ProftestSessionBindingPort
from andromeda.shared.contracts.errors import ConflictError, ContractError, ErrorCode, NotFoundError

from ..database.models import ProftestAnalyticsEventModel, ProftestAnswerSessionModel, UserProfileModel


logger = logging.getLogger("andromeda.infrastructure.repositories.proftest_sessions")


class SqlAlchemyProftestSessionRepository(ProftestAnswerSessionRepository, ProftestAnalyticsWriter, ProftestSessionBindingPort):
    """Persist session state while keeping contracts independent from ORM."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_current(self, scope: ProfileScope) -> ProftestAnswerSession | None:
        logger.debug("proftest_session_read_start owner_kind=%s dialect=%s", scope.owner_kind, self._dialect)
        model = self._session.scalar(
            select(ProftestAnswerSessionModel)
            .where(ProftestAnswerSessionModel.owner_key == scope.owner_key, ProftestAnswerSessionModel.status.in_((SessionStatus.DRAFT.value, SessionStatus.COMPLETED.value)))
            .order_by(ProftestAnswerSessionModel.updated_at.desc())
        )
        if model is None:
            return None
        if _utc(model.expires_at) <= _now() and model.status == SessionStatus.DRAFT.value:
            model.status = SessionStatus.EXPIRED.value
            self._session.commit()
            logger.warning("proftest_session_read_empty outcome=expired")
            return None
        result = self._to_contract(model)
        logger.debug("proftest_session_read_complete revision=%d cursor=%d", result.revision, result.cursor)
        return result

    def start(self, scope: ProfileScope, *, question_set_version: str, current_question_id: str, expires_at: datetime) -> ProftestAnswerSession:
        existing = self.get_current(scope)
        if existing is not None and existing.status is SessionStatus.DRAFT:
            logger.info("proftest_session_start outcome=resumed revision=%d", existing.revision)
            return existing
        now = _now()
        session = ProftestAnswerSession(
            session_id=f"proftest-session:{uuid4().hex}",
            question_set_version=question_set_version,
            status=SessionStatus.DRAFT,
            cursor=0,
            interaction_count=0,
            current_question_id=current_question_id,
            revision=1,
            created_at=now,
            updated_at=now,
            expires_at=_utc(expires_at),
        )
        model = self._model_values(scope, session)
        try:
            self._session.add(ProftestAnswerSessionModel(**model))
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            concurrent = self.get_current(scope)
            if concurrent is not None:
                logger.warning("proftest_session_start outcome=concurrent_resume")
                return concurrent
            raise ConflictError("An active proftest session already exists") from exc
        logger.info("proftest_session_start outcome=created revision=1")
        return session

    def bind_anonymous_session_to_account(self, scope: ProfileScope, account_id: str) -> ProfileBindingOutcome:
        """Move an anonymous draft only when the account has no current owner state."""

        if scope.account_id is not None:
            logger.warning("proftest_session_binding_rejected outcome=non_anonymous_scope")
            return ProfileBindingOutcome.NO_ANONYMOUS_PROFILE
        anonymous = self._session.scalar(
            select(ProftestAnswerSessionModel)
            .where(
                ProftestAnswerSessionModel.owner_key == scope.owner_key,
                ProftestAnswerSessionModel.account_id.is_(None),
                ProftestAnswerSessionModel.status == SessionStatus.DRAFT.value,
            )
            .order_by(ProftestAnswerSessionModel.updated_at.desc())
            .with_for_update()
        )
        account_profile = self._session.scalar(
            select(UserProfileModel)
            .where(UserProfileModel.account_id == account_id)
            .with_for_update()
        )
        account_draft = self._session.scalar(
            select(ProftestAnswerSessionModel)
            .where(ProftestAnswerSessionModel.owner_key == account_id, ProftestAnswerSessionModel.status == SessionStatus.DRAFT.value)
            .with_for_update()
        )
        if account_profile is not None or account_draft is not None:
            logger.info("proftest_session_binding_complete outcome=account_state_kept")
            return ProfileBindingOutcome.ACCOUNT_PROFILE_KEPT
        if anonymous is None or _utc(anonymous.expires_at) <= _now():
            logger.info("proftest_session_binding_complete outcome=no_anonymous_draft")
            return ProfileBindingOutcome.NO_ANONYMOUS_PROFILE
        try:
            anonymous.owner_key = account_id
            anonymous.account_id = account_id
            anonymous.session_key_hash = None
            self._session.execute(
                update(ProftestAnalyticsEventModel)
                .where(ProftestAnalyticsEventModel.owner_key == scope.owner_key)
                .values(owner_key=account_id)
            )
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("proftest_session_binding_failed outcome=storage_error dialect=%s", self._dialect, exc_info=exc)
            raise
        logger.info("proftest_session_binding_complete outcome=bound")
        return ProfileBindingOutcome.BOUND

    def save(self, scope: ProfileScope, session: ProftestAnswerSession, *, expected_revision: int) -> ProftestAnswerSession:
        model = self._locked(scope, session.session_id)
        if model.revision != expected_revision:
            self._session.rollback()
            logger.warning("proftest_session_save_rejected outcome=stale_revision expected=%d actual=%d", expected_revision, model.revision)
            raise ConflictError("Proftest session revision is stale")
        if model.status != SessionStatus.DRAFT.value:
            self._session.rollback()
            raise ConflictError("Only a draft proftest session can be saved")
        updated = session.model_copy(update={"revision": model.revision + 1, "updated_at": _now()})
        for field, value in self._model_values(scope, updated).items():
            setattr(model, field, value)
        try:
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("proftest_session_save_failed dialect=%s", self._dialect, exc_info=exc)
            raise
        logger.info("proftest_session_save_complete revision=%d cursor=%d", updated.revision, updated.cursor)
        return updated

    def complete(self, scope: ProfileScope, session: ProftestAnswerSession, profile: UserProfile, *, expires_at: datetime) -> tuple[ProftestAnswerSession, UserProfileSnapshot]:
        model = self._locked(scope, session.session_id)
        if model.status == SessionStatus.COMPLETED.value:
            existing_profile = self._profile_snapshot(scope)
            if existing_profile is None:
                raise ContractError(ErrorCode.CONTRACT_ERROR, "Completed proftest session has no profile")
            return self._to_contract(model), existing_profile
        if model.revision != session.revision:
            self._session.rollback()
            raise ConflictError("Proftest session revision is stale")
        now = _now()
        completed = session.model_copy(
            update={
                "status": SessionStatus.COMPLETED,
                "current_question_id": None,
                "revision": model.revision + 1,
                "updated_at": now,
                "expires_at": _utc(expires_at),
            }
        )
        profile_model = self._upsert_profile(scope, profile, expires_at=_utc(expires_at), now=now)
        for field, value in self._model_values(scope, completed).items():
            setattr(model, field, value)
        try:
            self._session.flush()
            snapshot = self._profile_snapshot_from_model(profile_model)
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("proftest_session_complete_failed dialect=%s", self._dialect, exc_info=exc)
            raise
        logger.info("proftest_session_complete revision=%d profile_revision=%d", completed.revision, snapshot.revision)
        return completed, snapshot

    def append(self, scope: ProfileScope, events: tuple[ProftestAnalyticsEvent, ...]) -> int:
        if not events:
            return 0
        purge_result = self._session.execute(delete(ProftestAnalyticsEventModel).where(ProftestAnalyticsEventModel.expires_at <= _now()))
        purged = int(getattr(purge_result, "rowcount", 0) or 0)
        if purged:
            logger.info("proftest_analytics_retention_purged count=%d", purged)
        inserted = 0
        for event in events:
            if self._session.get(ProftestAnalyticsEventModel, event.event_id) is not None:
                continue
            self._session.add(
                ProftestAnalyticsEventModel(
                    event_id=event.event_id,
                    session_id=event.session_id,
                    owner_key=scope.owner_key,
                    question_set_version=event.question_set_version,
                    event_type=event.event_type.value,
                    payload_json=event.payload,
                    occurred_at=_utc(event.occurred_at),
                    expires_at=_utc(event.expires_at),
                )
            )
            inserted += 1
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            logger.warning("proftest_analytics_append_rejected outcome=duplicate_or_race")
            raise ConflictError("Analytics event batch could not be accepted") from exc
        logger.info("proftest_analytics_append_complete inserted=%d deduplicated=%d", inserted, len(events) - inserted)
        return inserted

    def aggregates(self, *, question_set_version: str) -> dict[str, int | float]:
        rows = self._session.execute(
            select(ProftestAnalyticsEventModel.event_type, ProftestAnalyticsEventModel.payload_json)
            .where(ProftestAnalyticsEventModel.question_set_version == question_set_version, ProftestAnalyticsEventModel.expires_at > _now())
        ).all()
        result: dict[str, int | float] = {}
        response_times: list[float] = []
        event_count = 0
        for event_type, payload in rows:
            event_count += 1
            result[event_type] = int(result.get(event_type, 0)) + 1
            if isinstance(payload, dict):
                duration = payload.get("durationMs")
                if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
                    response_times.append(float(duration))
                for payload_key, result_key in (("uncertainty", "uncertain_answers"), ("changed", "changed_answers"), ("top3Changed", "top3_changes")):
                    if payload.get(payload_key) is True:
                        result[result_key] = int(result.get(result_key, 0)) + 1
                if payload.get("adaptiveCount") is not None:
                    result["adaptive_questions"] = int(result.get("adaptive_questions", 0)) + 1
        # Keep the row count separate from derived counters. Summing the
        # result mapping would count uncertainty/answer-change metrics twice.
        result["total_events"] = event_count
        result["completion_rate"] = round(result.get(AnalyticsEventType.TEST_COMPLETED.value, 0) / max(1, result.get(AnalyticsEventType.TEST_STARTED.value, 0)), 4)
        result["response_time_median_ms"] = _median(response_times)
        return result

    def _locked(self, scope: ProfileScope, session_id: str) -> ProftestAnswerSessionModel:
        model = self._session.scalar(
            select(ProftestAnswerSessionModel)
            .where(ProftestAnswerSessionModel.session_id == session_id, ProftestAnswerSessionModel.owner_key == scope.owner_key)
            .with_for_update()
        )
        if model is None:
            self._session.rollback()
            raise NotFoundError("Proftest session was not found")
        if _utc(model.expires_at) <= _now() and model.status == SessionStatus.DRAFT.value:
            model.status = SessionStatus.EXPIRED.value
            self._session.commit()
            raise ConflictError("Proftest session has expired")
        return model

    @staticmethod
    def _model_values(scope: ProfileScope, session: ProftestAnswerSession) -> dict[str, object]:
        return {
            "session_id": session.session_id,
            "owner_key": scope.owner_key,
            "session_key_hash": scope.session_key_hash if scope.account_id is None else None,
            "account_id": scope.account_id,
            "question_set_version": session.question_set_version,
            "status": session.status.value,
            "state_json": {
                "answer_set": session.answer_set.model_dump(mode="json"),
                "adaptive_questions": [question.model_dump(mode="json") for question in session.adaptive_questions],
                "adaptive_state": session.adaptive_state.model_dump(mode="json") if session.adaptive_state is not None else None,
                "current_question_id": session.current_question_id,
                "stale_question_ids": list(session.stale_question_ids),
            },
            "cursor": session.cursor,
            "interaction_count": session.interaction_count,
            "revision": session.revision,
            "created_at": _utc(session.created_at),
            "updated_at": _utc(session.updated_at),
            "expires_at": _utc(session.expires_at),
        }

    @staticmethod
    def _to_contract(model: ProftestAnswerSessionModel) -> ProftestAnswerSession:
        try:
            state = model.state_json if isinstance(model.state_json, dict) else {}
            current_question_id = state.get("current_question_id")
            stale_question_ids = state.get("stale_question_ids", ())
            raw_adaptive_questions = state.get("adaptive_questions", ())
            raw_adaptive_state = state.get("adaptive_state")
            adaptive_questions = tuple(
                Question.model_validate(item, strict=False)
                for item in raw_adaptive_questions
                if isinstance(item, dict)
            ) if isinstance(raw_adaptive_questions, (list, tuple)) else ()
            adaptive_state = AdaptiveState.model_validate(raw_adaptive_state, strict=False) if isinstance(raw_adaptive_state, dict) else None
            return ProftestAnswerSession(
                session_id=model.session_id,
                question_set_version=model.question_set_version,
                status=SessionStatus(model.status),
                answer_set=_answer_set_from_state(state),
                adaptive_questions=adaptive_questions,
                adaptive_state=adaptive_state,
                cursor=model.cursor,
                interaction_count=model.interaction_count,
                current_question_id=current_question_id if isinstance(current_question_id, str) else None,
                stale_question_ids=tuple(item for item in stale_question_ids if isinstance(item, str)) if isinstance(stale_question_ids, (list, tuple)) else (),
                revision=model.revision,
                created_at=_utc(model.created_at),
                updated_at=_utc(model.updated_at),
                expires_at=_utc(model.expires_at),
            )
        except (TypeError, ValueError) as exc:
            logger.exception("proftest_session_contract_error outcome=invalid_persisted_state", exc_info=exc)
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Persisted proftest session is invalid") from exc

    def _upsert_profile(self, scope: ProfileScope, profile: UserProfile, *, expires_at: datetime, now: datetime) -> UserProfileModel:
        model = self._session.scalar(
            select(UserProfileModel)
            .where(UserProfileModel.account_id == scope.account_id if scope.account_id is not None else (UserProfileModel.account_id.is_(None) & (UserProfileModel.session_key_hash == scope.session_key_hash)))
            .with_for_update()
        )
        if model is None:
            model = UserProfileModel(
                profile_id=f"profile:{uuid4().hex}",
                session_key_hash=scope.session_key_hash if scope.account_id is None else None,
                account_id=scope.account_id,
                profile_json=profile.model_dump(mode="json"),
                revision=1,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
            )
            self._session.add(model)
        else:
            model.profile_json = profile.model_dump(mode="json")
            model.revision += 1
            model.updated_at = now
            model.expires_at = expires_at
        return model

    def _profile_snapshot(self, scope: ProfileScope) -> UserProfileSnapshot | None:
        model = self._session.scalar(
            select(UserProfileModel).where(UserProfileModel.account_id == scope.account_id if scope.account_id is not None else (UserProfileModel.account_id.is_(None) & (UserProfileModel.session_key_hash == scope.session_key_hash)))
        )
        return None if model is None else self._profile_snapshot_from_model(model)

    @staticmethod
    def _profile_snapshot_from_model(model: UserProfileModel) -> UserProfileSnapshot:
        return UserProfileSnapshot(
            profile_id=model.profile_id,
            profile=UserProfile.model_validate(model.profile_json, strict=False),
            revision=model.revision,
            created_at=_utc(model.created_at),
            updated_at=_utc(model.updated_at),
            expires_at=_utc(model.expires_at),
        )

    @property
    def _dialect(self) -> str:
        return self._session.get_bind().dialect.name


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 2)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def _answer_set_from_state(state: dict[str, object]) -> AnswerSet:
    raw = state.get("answer_set", {})
    if not isinstance(raw, dict):
        raise ValueError("answer_set state must be an object")
    answers: list[Answer] = []
    for item in raw.get("answers", []):
        if not isinstance(item, dict):
            raise ValueError("answer state must be an object")
        raw_intensity = item.get("intensity")
        answers.append(
            Answer(
                question_id=str(item["question_id"]),
                option_ids=tuple(str(value) for value in item.get("option_ids", [])),
                intensity=None if raw_intensity is None else Decimal(str(raw_intensity)),
                status=AnswerStatus(str(item.get("status", AnswerStatus.ANSWERED.value))),
            )
        )
    adaptive_answers: list[AdaptiveAnswer] = []
    for item in raw.get("adaptive_answers", []):
        if not isinstance(item, dict):
            raise ValueError("adaptive answer state must be an object")
        adaptive_answers.append(
            AdaptiveAnswer(
                question_id=str(item["question_id"]),
                option_id=str(item["option_id"]),
                dimension=str(item["dimension"]),
            )
        )
    return AnswerSet(answers=tuple(answers), adaptive_answers=tuple(adaptive_answers))


__all__ = ["SqlAlchemyProftestSessionRepository"]
