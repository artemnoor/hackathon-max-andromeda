"""Conversation turn orchestration with optimistic revision checks."""

from __future__ import annotations

from datetime import UTC, datetime

from andromeda.shared.contracts.errors import ConflictError, ContractError, ErrorCode

from ..contracts.public import QuerySession
from ..domain.session import merge_parsed_query
from .rule_parser import RuleBasedQueryParser


class ConversationEngine:
    def __init__(self, parser: RuleBasedQueryParser | None = None) -> None:
        self._parser = parser or RuleBasedQueryParser()

    def apply(
        self,
        session: QuerySession,
        text: str,
        *,
        expected_revision: int | None = None,
        now: datetime | None = None,
    ) -> QuerySession:
        if expected_revision is not None and expected_revision != session.revision:
            raise ConflictError("query session revision is stale")
        timestamp = now or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ContractError(ErrorCode.INVALID_QUERY, "conversation timestamp must be timezone-aware")
        if timestamp >= session.expires_at:
            raise ContractError(ErrorCode.CONFLICT, "query session has expired")
        return merge_parsed_query(
            session,
            self._parser.parse(text),
            updated_at=timestamp,
            parser_version=self._parser.version,
        )


__all__ = ["ConversationEngine"]
