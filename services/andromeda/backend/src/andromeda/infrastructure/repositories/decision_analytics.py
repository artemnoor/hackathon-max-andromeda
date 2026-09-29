"""SQLAlchemy adapter for owner-scoped decision analytics."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from collections import defaultdict
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from andromeda.modules.decision.contracts.public import DecisionAnalyticsEvent, DecisionAnalyticsFunnel, DecisionAnalyticsWriter
from andromeda.modules.decision.repository.ports import DecisionAnalyticsReader
from andromeda.modules.proftest.contracts.public import ProfileScope

from ..database.models import DecisionAnalyticsEventModel


logger = logging.getLogger("andromeda.infrastructure.repositories.decision_analytics")


class SqlAlchemyDecisionAnalyticsRepository(DecisionAnalyticsWriter, DecisionAnalyticsReader):
    """Append-only analytics writer with TTL cleanup and per-owner dedupe."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, scope: ProfileScope, events: tuple[DecisionAnalyticsEvent, ...]) -> int:
        if not events:
            return 0
        now = _now()
        purge_result = self._session.execute(
            delete(DecisionAnalyticsEventModel).where(DecisionAnalyticsEventModel.expires_at <= now)
        )
        purged = int(getattr(purge_result, "rowcount", 0) or 0)
        if purged:
            logger.info("decision_analytics_retention_purged count=%d", purged)

        inserted = 0
        for event in events:
            if event.expires_at <= now:
                continue
            identity = (scope.owner_key, event.event_id)
            if self._session.get(DecisionAnalyticsEventModel, identity) is not None:
                continue
            model = DecisionAnalyticsEventModel(
                owner_key=scope.owner_key,
                event_id=event.event_id,
                session_key_hash=scope.session_key_hash if scope.account_id is None else None,
                account_id=scope.account_id,
                event_type=event.event_type.value,
                payload_json=event.payload.model_dump(mode="json", exclude_none=True),
                occurred_at=_utc(event.occurred_at),
                created_at=now,
                expires_at=_utc(event.expires_at),
            )
            try:
                # A savepoint makes a concurrent duplicate harmless without
                # rolling back unrelated rows in the caller's transaction.
                with self._session.begin_nested():
                    self._session.add(model)
                    self._session.flush()
                inserted += 1
            except IntegrityError:
                logger.info("decision_analytics_append_deduplicated outcome=concurrent")
        self._session.commit()
        logger.info(
            "decision_analytics_append_complete owner_kind=%s inserted=%d deduplicated=%d",
            scope.owner_kind,
            inserted,
            len(events) - inserted,
        )
        return inserted

    def funnel(self) -> DecisionAnalyticsFunnel:
        """Return aggregate counts without exposing event payloads."""

        rows = self._session.execute(
            select(
                DecisionAnalyticsEventModel.owner_key,
                DecisionAnalyticsEventModel.event_type,
                DecisionAnalyticsEventModel.payload_json,
            ).where(DecisionAnalyticsEventModel.expires_at > _now())
        ).all()
        owners_by_type: dict[str, set[str]] = defaultdict(set)
        shortlist_sizes: list[int] = []
        for owner_key, event_type, payload in rows:
            owners_by_type[str(event_type)].add(str(owner_key))
            if str(event_type) == "shortlist_size_changed":
                value = payload.get("shortlist_size_after") if isinstance(payload, dict) else None
                if isinstance(value, int) and 0 <= value <= 20:
                    shortlist_sizes.append(value)

        sessions = len(owners_by_type["decision_session_started"])

        def count(event_type: str) -> int:
            return len(owners_by_type[event_type])

        def conversion(value: int) -> float | None:
            return round(value * 100 / sessions, 2) if sessions else None

        return DecisionAnalyticsFunnel(
            decision_sessions=sessions,
            shortlist_started=count("program_added_to_shortlist"),
            comparison_started=count("comparison_started"),
            comparison_completed=count("comparison_completed"),
            suggestion_shown=count("system_suggestion_shown"),
            suggestion_accepted=count("system_suggestion_accepted"),
            final_choice_selected=count("final_choice_selected"),
            average_shortlist_size=round(sum(shortlist_sizes) / len(shortlist_sizes), 2) if shortlist_sizes else None,
            shortlist_conversion_percent=conversion(count("program_added_to_shortlist")),
            comparison_conversion_percent=conversion(count("comparison_completed")),
            final_choice_conversion_percent=conversion(count("final_choice_selected")),
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


__all__ = ["SqlAlchemyDecisionAnalyticsRepository"]
