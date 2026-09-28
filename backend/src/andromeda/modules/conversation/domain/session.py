"""Pure session merge and slot-derivation logic."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

from ...admissions.contracts.public import FundingType
from ...entity_resolution.contracts.public import ResolutionEntityType
from ..contracts.public import (
    CONVERSATION_PARSER_VERSION,
    AdmissionUniversityScope,
    ConversationIntent,
    ConversationSlot,
    ExamScore,
    FactOrigin,
    NextAction,
    ParsedQuery,
    PolicyQueryContext,
    PolicyQueryFocus,
    QueryFact,
    QueryFrame,
    QuerySession,
)


def merge_parsed_query(
    session: QuerySession,
    parsed: ParsedQuery,
    *,
    updated_at: datetime,
    parser_version: str = CONVERSATION_PARSER_VERSION,
) -> QuerySession:
    if updated_at.tzinfo is None:
        raise ValueError("updated_at must be timezone-aware")
    entities = {key: tuple(values) for key, values in session.entities.items()}
    if parsed.university_queries:
        entities[ResolutionEntityType.UNIVERSITY] = tuple(
            dict.fromkeys((*entities.get(ResolutionEntityType.UNIVERSITY, ()), *parsed.university_queries))
        )
    if parsed.direction_queries:
        entities[ResolutionEntityType.DIRECTION] = tuple(
            dict.fromkeys((*entities.get(ResolutionEntityType.DIRECTION, ()), *parsed.direction_queries))
        )
    if parsed.program_queries:
        entities[ResolutionEntityType.PROGRAM] = tuple(
            dict.fromkeys((*entities.get(ResolutionEntityType.PROGRAM, ()), *parsed.program_queries))
        )
    known_slots = dict(session.known_slots)
    confirmed_parameters = dict(session.confirmed_parameters)
    inferred_parameters = dict(session.inferred_parameters)
    if parsed.total_score is not None:
        known_slots["total_score"] = parsed.total_score
        confirmed_parameters["total_score"] = QueryFact(value=parsed.total_score, origin=FactOrigin.EXPLICIT_USER, confirmed=True)
    if parsed.exam_scores:
        known_slots["exam_scores"] = tuple(parsed.exam_scores)
        confirmed_parameters["exam_scores"] = QueryFact(value=tuple(parsed.exam_scores), origin=FactOrigin.EXPLICIT_USER, confirmed=True)
    if parsed.funding_type is not None:
        known_slots["funding_type"] = parsed.funding_type
        confirmed_parameters["funding_type"] = QueryFact(
            value=parsed.funding_type,
            origin=FactOrigin.EXPLICIT_USER,
            confirmed=True,
        )
        inferred_parameters.pop("funding_type", None)
    if parsed.study_form is not None:
        known_slots["study_form"] = parsed.study_form
        known_slots.pop("study_form_ambiguous", None)
        confirmed_parameters["study_form"] = QueryFact(
            value=parsed.study_form,
            origin=FactOrigin.EXPLICIT_USER,
            confirmed=True,
        )
        inferred_parameters.pop("study_form", None)
    elif parsed.study_form_ambiguous:
        known_slots["study_form_ambiguous"] = True
    if parsed.admission_year is not None:
        known_slots["admission_year"] = parsed.admission_year
        confirmed_parameters["admission_year"] = QueryFact(
            value=parsed.admission_year,
            origin=FactOrigin.EXPLICIT_USER,
            confirmed=True,
        )
        inferred_parameters.pop("admission_year", None)
    if parsed.semester is not None:
        confirmed_parameters["semester"] = QueryFact(value=parsed.semester, origin=FactOrigin.EXPLICIT_USER, confirmed=True)
    if parsed.course_year is not None:
        confirmed_parameters["course_year"] = QueryFact(value=parsed.course_year, origin=FactOrigin.EXPLICIT_USER, confirmed=True)
    admission_university_scope = parsed.admission_university_scope or session.admission_university_scope
    if parsed.admission_university_scope is not None:
        entities.pop(ResolutionEntityType.UNIVERSITY, None)
        confirmed_parameters["admission_university_scope"] = QueryFact(
            value=parsed.admission_university_scope,
            origin=FactOrigin.EXPLICIT_USER,
            confirmed=True,
        )
    elif parsed.university_queries:
        admission_university_scope = None
        confirmed_parameters.pop("admission_university_scope", None)
    if parsed.aggregation is not None:
        inferred_parameters["aggregation"] = QueryFact(
            value=parsed.aggregation,
            origin=FactOrigin.DETERMINISTIC_INFERENCE,
            confirmed=False,
        )
    metrics = tuple(dict.fromkeys((*session.metrics, *parsed.metric_codes)))
    policy_follow_up = _is_policy_follow_up(session, parsed)
    policy_query_context = _merge_policy_context(
        session.policy_query_context,
        parsed.policy_query_context,
        keep_existing=policy_follow_up,
        referential_follow_up=_is_referential_policy_follow_up(parsed.unresolved_text),
    )
    if parsed.policy_query_context is not None or policy_follow_up:
        intent = ConversationIntent.KNOWLEDGE_POLICY_QUERY
    else:
        intent = parsed.intent if parsed.intent is not ConversationIntent.UNKNOWN else session.intent
    scope = parsed.scope or session.scope
    aggregation = parsed.aggregation or session.aggregation
    stored_total_score = cast(Decimal | None, known_slots.get("total_score"))
    stored_exam_scores = cast(tuple[ExamScore, ...], known_slots.get("exam_scores", ()))
    missing_slots, next_action = _derive_slots(
        intent,
        metrics,
        parsed.total_score if parsed.total_score is not None else stored_total_score,
        parsed.exam_scores or stored_exam_scores,
        entities,
        admission_university_scope,
        known_slots,
        confirmed_parameters,
        policy_query_context,
    )
    candidate = session.model_copy(
        update={
            "intent": intent,
            "admission_university_scope": admission_university_scope,
            "parser_version": parser_version,
            "frame": QueryFrame(
                intent=intent,
                admission_university_scope=admission_university_scope,
                entities=entities,
                metrics=metrics,
                scope=scope,
                scope_ids=session.scope_ids,
                filters=session.filters,
                aggregation=aggregation,
                semester=parsed.semester or _fact_int(confirmed_parameters, "semester"),
                course_year=parsed.course_year or _fact_int(confirmed_parameters, "course_year"),
                missing_fields=missing_slots,
            ),
            "entities": entities,
            "metrics": metrics,
            "scope": scope,
            "aggregation": aggregation,
            "known_slots": known_slots,
            "confirmed_parameters": confirmed_parameters,
            "inferred_parameters": inferred_parameters,
            "policy_query_context": policy_query_context,
            "missing_slots": missing_slots,
            "next_action": next_action,
            "last_action": next_action,
            "updated_at": updated_at,
            "revision": session.revision + 1,
        }
    )
    if candidate.model_dump(exclude={"revision", "updated_at"}) == session.model_dump(exclude={"revision", "updated_at"}):
        return session
    return candidate


def _fact_int(facts: dict[str, QueryFact], key: str) -> int | None:
    fact = facts.get(key)
    return fact.value if fact is not None and isinstance(fact.value, int) else None


def _derive_slots(
    intent: ConversationIntent,
    metrics: tuple[str, ...],
    total_score: Decimal | None,
    exam_scores: tuple[ExamScore, ...],
    entities: dict[ResolutionEntityType, tuple[str, ...]],
    admission_university_scope: AdmissionUniversityScope | None,
    known_slots: dict[str, object],
    confirmed_parameters: dict[str, QueryFact],
    policy_query_context: PolicyQueryContext | None,
) -> tuple[tuple[ConversationSlot, ...], NextAction]:
    if intent is ConversationIntent.KNOWLEDGE_POLICY_QUERY:
        if policy_query_context is None:
            return (ConversationSlot.ENTITY,), NextAction.CLARIFY
        if policy_query_context.focus in {
            PolicyQueryFocus.APPLICABILITY,
            PolicyQueryFocus.IMPACT,
        }:
            year_fact = confirmed_parameters.get("admission_year")
            if (
                year_fact is None
                or year_fact.origin is not FactOrigin.EXPLICIT_USER
                or not year_fact.confirmed
                or not isinstance(year_fact.value, int)
            ):
                return (ConversationSlot.ADMISSION_YEAR,), NextAction.ASK_FOR_ADMISSION_YEAR
        return (), NextAction.EXECUTE_QUERY
    if intent is ConversationIntent.ADMISSION_SEARCH:
        if total_score is None and not exam_scores:
            return (ConversationSlot.TOTAL_SCORE, ConversationSlot.EXAMS), NextAction.ASK_FOR_EXAMS
        if not exam_scores:
            return (ConversationSlot.EXAMS,), NextAction.ASK_FOR_EXAMS
        if (
            not entities.get(ResolutionEntityType.UNIVERSITY)
            and admission_university_scope is not AdmissionUniversityScope.ANY_UNIVERSITY
        ):
            return (ConversationSlot.UNIVERSITY_SCOPE,), NextAction.ASK_FOR_UNIVERSITY_SCOPE
        if not isinstance(known_slots.get("funding_type"), FundingType):
            return (ConversationSlot.FUNDING,), NextAction.ASK_FOR_FUNDING
        if known_slots.get("study_form_ambiguous") is True:
            return (ConversationSlot.STUDY_FORM,), NextAction.ASK_FOR_STUDY_FORM
        return (), NextAction.EXECUTE_QUERY
    if not metrics:
        return (ConversationSlot.METRIC,), NextAction.ASK_FOR_METRIC
    if not entities.get(ResolutionEntityType.PROGRAM) and not entities.get(ResolutionEntityType.UNIVERSITY) and not entities.get(ResolutionEntityType.DIRECTION):
        return (ConversationSlot.ENTITY,), NextAction.ASK_FOR_ENTITY
    return (), NextAction.EXECUTE_QUERY


def _is_policy_follow_up(session: QuerySession, parsed: ParsedQuery) -> bool:
    if session.policy_query_context is None or parsed.policy_query_context is not None:
        return False
    if parsed.intent is ConversationIntent.UNKNOWN:
        return True
    if parsed.intent is not ConversationIntent.ADMISSION_SEARCH:
        return False
    if parsed.total_score is not None or parsed.exam_scores or parsed.metric_codes:
        return False
    if any(marker in parsed.unresolved_text.casefold() for marker in ("куда", "прохожу", "сравни")):
        return False
    return any(
        value is not None
        for value in (
            parsed.admission_year,
            parsed.funding_type,
            parsed.study_form,
            parsed.admission_university_scope,
        )
    ) or bool(parsed.university_queries or parsed.direction_queries or parsed.program_queries)


def _is_referential_policy_follow_up(text: str) -> bool:
    normalized = text.casefold()
    return any(marker in normalized for marker in ("это", "этот", "эта", "этого", "меня", "мне"))


def _merge_policy_context(
    current: PolicyQueryContext | None,
    parsed: PolicyQueryContext | None,
    *,
    keep_existing: bool,
    referential_follow_up: bool,
) -> PolicyQueryContext | None:
    if parsed is None:
        return current if keep_existing else None
    if current is None or not referential_follow_up:
        return parsed
    updates = {
        field: getattr(parsed, field) or getattr(current, field)
        for field in (
            "mentioned_effective_year",
            "claim_predicate",
            "valid_as_of",
            "as_known_at",
            "source_id",
            "change_event_id",
            "policy_rule_id",
            "admission_cycle_id",
            "resolution_trace_id",
            "impact_preview_id",
            "what_if_rule_id",
        )
    }
    return current.model_copy(update={"focus": parsed.focus, **updates})


__all__ = ["merge_parsed_query"]
