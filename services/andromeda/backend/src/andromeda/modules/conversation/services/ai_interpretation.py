"""Validation and merge for AI-extracted, non-canonical query candidates."""

from __future__ import annotations

import re
from decimal import Decimal

from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.modules.conversation.contracts.language import (
    AssistantClarificationRequest,
    AssistantQueryInterpretation,
)
from andromeda.modules.conversation.contracts.public import (
    AdmissionUniversityScope,
    ConversationIntent,
    ConversationSlot,
    ParsedQuery,
)
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode

from .program_preferences import (
    area_is_explicitly_avoided as _area_is_explicitly_avoided,
)
from .program_preferences import (
    area_is_in_text as _area_is_in_text,
)


def merge_ai_interpretation(
    parsed: ParsedQuery,
    interpretation: AssistantQueryInterpretation,
    *,
    text: str,
    allowed_metrics: tuple[str, ...],
    current_intent: ConversationIntent | None,
    missing_slots: tuple[ConversationSlot, ...],
) -> ParsedQuery:
    """Use model candidates only when they are grounded in this user turn."""

    normalized = _normalize(text)
    entities = tuple(
        item
        for item in interpretation.entities
        if _phrase_is_in_text(item.query, normalized)
        and not _is_generic_reference_entity(item.query)
        and not _is_metric_only_entity_phrase(item.query, parsed.metric_codes)
        and not _is_discovery_area_entity(
            item.query,
            parsed=parsed,
            interpretation=interpretation,
            current_intent=current_intent,
            missing_slots=missing_slots,
        )
        and not (
            interpretation.compare_with_any_other_direction
            and _is_generic_alternative_phrase(item.query)
        )
    )
    parsed_entities = {
        "university_queries": _merge_entity_queries(
            parsed.university_queries,
            tuple(
                item.query for item in entities if item.entity_type.value == "university"
            ),
            user_text=normalized,
        ),
        "direction_queries": _merge_entity_queries(
            parsed.direction_queries,
            tuple(
                item.query for item in entities if item.entity_type.value == "direction"
            ),
            user_text=normalized,
        ),
        "program_queries": _merge_entity_queries(
            parsed.program_queries,
            tuple(
                item.query for item in entities if item.entity_type.value == "program"
            ),
            user_text=normalized,
        ),
    }

    metric_codes = tuple(
        dict.fromkeys(
            (
                *parsed.metric_codes,
                *(
                    code
                    for code in interpretation.metric_codes
                    if code in allowed_metrics
                ),
            )
        )
    )
    exam_scores = tuple(
        score
        for score in interpretation.exam_scores
        if _number_is_in_text(score.score, normalized)
        and _subject_is_in_text(score.subject, normalized)
    )
    avoided_areas = tuple(
        area
        for area in interpretation.avoided_areas
        if _area_is_in_text(area, normalized)
        and _area_is_explicitly_avoided(area, normalized)
    )
    avoided_set = set(avoided_areas)
    comparative_criteria = bool(metric_codes) and any(
        marker in normalized
        for marker in (
            "из них", "какая из", "какой из", "где больше", "где меньше",
            "а где", "сравни", "сравнить",
        )
    )
    model_preferred_areas = (
        () if comparative_criteria else interpretation.preferred_areas
    )
    preferred_areas = tuple(
        area
        for area in dict.fromkeys(
            (*parsed.preferred_areas, *model_preferred_areas)
        )
        if _area_is_in_text(area, normalized)
        and area not in avoided_set
        and not _area_is_explicitly_avoided(area, normalized)
    )
    total_score = interpretation.total_score
    if total_score is not None and not _number_is_in_text(total_score, normalized):
        total_score = None

    admission_year = interpretation.admission_year
    if admission_year is not None and not re.search(
        rf"(?<!\d){admission_year}(?!\d)", normalized
    ):
        admission_year = None
    funding_type = (
        interpretation.funding_type
        if _funding_is_explicit(interpretation.funding_type, normalized)
        else None
    )
    study_form = (
        interpretation.study_form
        if _study_form_is_explicit(interpretation.study_form, normalized)
        else None
    )
    university_scope = (
        interpretation.admission_university_scope
        if _university_scope_is_explicit(
            interpretation.admission_university_scope, normalized
        )
        else None
    )
    intent = (
        parsed.intent
        if parsed.intent is not ConversationIntent.UNKNOWN
        else interpretation.intent
    )
    if parsed.policy_query_context is not None:
        intent = ConversationIntent.KNOWLEDGE_POLICY_QUERY
    elif current_intent is not None and missing_slots:
        if interpretation.starts_new_task and interpretation.intent is not ConversationIntent.UNKNOWN:
            intent = interpretation.intent
        elif parsed.intent is not ConversationIntent.UNKNOWN and parsed.intent is not current_intent:
            intent = parsed.intent
        else:
            intent = current_intent

    scores_by_subject = {
        item.subject.casefold(): item for item in parsed.exam_scores
    }
    for item in exam_scores:
        scores_by_subject.setdefault(item.subject.casefold(), item)

    return parsed.model_copy(
        update={
            "intent": intent,
            "starts_new_task": interpretation.starts_new_task,
            "olympiad_query": (
                interpretation.olympiad_query
                if interpretation.olympiad_query
                and _phrase_is_in_text(interpretation.olympiad_query, normalized)
                else parsed.olympiad_query
            ),
            "olympiad_profile_query": (
                interpretation.olympiad_profile_query
                if interpretation.olympiad_profile_query
                and _phrase_is_in_text(interpretation.olympiad_profile_query, normalized)
                else parsed.olympiad_profile_query
            ),
            "olympiad_result_year": (
                interpretation.olympiad_result_year
                if interpretation.olympiad_result_year is not None
                and re.search(
                    rf"(?<!\d){interpretation.olympiad_result_year}(?!\d)",
                    normalized,
                )
                else parsed.olympiad_result_year
            ),
            "olympiad_level": (
                interpretation.olympiad_level
                if interpretation.olympiad_level is not None
                and re.search(
                    rf"(?<!\d){interpretation.olympiad_level}(?!\d)\s*(?:-?го|ого)?\s*уровн",
                    normalized,
                )
                else parsed.olympiad_level
            ),
            "olympiad_result_type": (
                interpretation.olympiad_result_type
                if interpretation.olympiad_result_type is not None
                and (
                    "победител" in normalized
                    or "призер" in normalized
                )
                else parsed.olympiad_result_type
            ),
            **parsed_entities,
            "metric_codes": metric_codes,
            "total_score": (
                total_score if total_score is not None else parsed.total_score
            ),
            "exam_scores": tuple(scores_by_subject.values()),
            "preferred_areas": preferred_areas,
            "avoided_areas": avoided_areas,
            "funding_type": funding_type or parsed.funding_type,
            "study_form": study_form or parsed.study_form,
            "study_form_ambiguous": (
                interpretation.study_form_ambiguous
                and _study_form_is_ambiguous(normalized)
            )
            or parsed.study_form_ambiguous,
            "admission_year": admission_year or parsed.admission_year,
            "admission_university_scope": (
                university_scope or parsed.admission_university_scope
            ),
            "unresolved_text": parsed.unresolved_text or text.strip()[:1_000],
        }
    )


def safe_unverified_answer(
    answer: str | None,
    *,
    user_message: str,
    intent: ConversationIntent,
    has_pending_slots: bool,
) -> str | None:
    """Keep generated general prose separate from supported domain operations."""

    if (
        not answer
        or intent is not ConversationIntent.UNKNOWN
        or has_pending_slots
        or len(answer) > 4_000
        or "http://" in answer.casefold()
        or "https://" in answer.casefold()
    ):
        return None
    user_numbers = set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", user_message))
    answer_numbers = set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", answer))
    if not answer_numbers.issubset(user_numbers):
        return None
    cleaned = " ".join(answer.split())
    return cleaned if cleaned else None


def is_explicit_any_other_request(text: str) -> bool:
    normalized = _normalize(text)
    return any(
        marker in normalized
        for marker in (
            "любой другой",
            "любым другим",
            "любое другое",
            "другое направление",
            "другую программу",
            "любой еще",
            "любую еще",
        )
    )


def clarification_is_grounded(
    question: str, request: AssistantClarificationRequest
) -> bool:
    if (
        "?" not in question
        or question[-1] not in {"?", ".", "!"}
        or len(question) > 512
        or "http://" in question.casefold()
        or "https://" in question.casefold()
    ):
        return False
    supplied_text = " ".join(
        (
            request.user_message,
            request.current_question,
            *request.available_options,
            *request.resolved_entities,
            *request.unresolved_entities,
        )
    )
    supplied_numbers = set(
        re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", supplied_text)
    )
    question_numbers = set(
        re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", question)
    )
    if not question_numbers.issubset(supplied_numbers):
        return False
    supplied_words = _normalize(supplied_text)
    introduced_names = tuple(
        match.group(0)
        for match in re.finditer(
            r"\b(?:[A-ZА-ЯЁ]{2,}|[A-ZА-ЯЁ][a-zа-яё]{2,})\b", question
        )
        if match.start() > 0
        and not question[: match.start()].rstrip().endswith((".", "?", "!", ":", "\n"))
    )
    return all(_normalize(name) in supplied_words for name in introduced_names)


def _merge_entity_queries(
    deterministic_queries: tuple[str, ...],
    model_queries: tuple[str, ...],
    *,
    user_text: str,
) -> tuple[str, ...]:
    """Keep grounded mentions and prefer the exact inflected phrase the user used."""

    merged: list[str] = []
    positions: dict[str, int] = {}
    for query in (*deterministic_queries, *model_queries):
        normalized = _normalize(query)
        key = _entity_query_dedup_key(normalized)
        if not normalized:
            continue
        if key not in positions:
            positions[key] = len(merged)
            merged.append(query)
            continue
        index = positions[key]
        prior = merged[index]
        prior_is_literal = _phrase_is_in_text(prior, user_text)
        candidate_is_literal = _phrase_is_in_text(query, user_text)
        if candidate_is_literal and not prior_is_literal:
            merged[index] = query
    return tuple(merged)


def _entity_query_dedup_key(normalized: str) -> str:
    """Collapse a single-word Russian case ending without merging distinct phrases."""

    if " " in normalized or not re.fullmatch(r"[a-zа-яё-]+", normalized):
        return normalized
    for suffix in ("ами", "ями", "ого", "ему", "ому", "ыми", "ими", "ах", "ях", "ам", "ям", "ом", "ем", "ой", "ий", "ый", "ая", "яя", "ое", "ее", "а", "я", "е", "и", "у", "ю"):
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 4:
            return normalized[: -len(suffix)]
    return normalized


def _is_discovery_area_entity(
    value: str,
    *,
    parsed: ParsedQuery,
    interpretation: AssistantQueryInterpretation,
    current_intent: ConversationIntent | None,
    missing_slots: tuple[ConversationSlot, ...],
) -> bool:
    intent = parsed.intent
    if intent is ConversationIntent.UNKNOWN:
        if current_intent is not None and missing_slots and not interpretation.starts_new_task:
            intent = current_intent
        else:
            intent = interpretation.intent
    if intent is not ConversationIntent.PROGRAM_DISCOVERY:
        return False
    if value.casefold().startswith(("program:", "direction:")):
        return False
    tokens = re.findall(r"[a-zа-яё0-9]+", _normalize(value))
    if not tokens or len(tokens) > 3:
        return False
    normalized_value = _normalize(value)
    return any(_area_is_in_text(area, normalized_value) for area in DisciplineAreaCode)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _phrase_is_in_text(phrase: str, normalized_text: str) -> bool:
    normalized_phrase = _normalize(phrase)
    return bool(normalized_phrase and normalized_phrase in normalized_text)


def _is_generic_alternative_phrase(value: str) -> bool:
    normalized = _normalize(value)
    return any(
        marker in normalized
        for marker in ("любой другой", "любым другим", "другое направление", "любой еще")
    )


def _is_generic_reference_entity(value: str) -> bool:
    normalized = _normalize(value)
    return normalized in {
        "их",
        "эти",
        "эти программы",
        "эти направления",
        "первые две",
        "первые два",
        "вторую",
        "из этого",
        "из них",
        "обе",
    }


def _is_metric_only_entity_phrase(
    value: str, parsed_metric_codes: tuple[str, ...]
) -> bool:
    if not parsed_metric_codes:
        return False
    aliases_by_metric = {
        "math_share": (
            "математическая нагрузка",
            "математике",
            "математики",
            "математик",
            "матан",
        ),
        "programming_share": ("программирован", "разработк", "кодинг"),
        "ai_share": (
            "искусственный интеллект",
            "искусственн интеллект",
            "машинное обучение",
            "машинн обучен",
            "ai",
        ),
        "physics_share": ("физик",),
        "business_share": ("бизнес",),
        "analytics_share": ("аналитик",),
    }
    remainder = _normalize(value)
    for metric_code in parsed_metric_codes:
        for alias in aliases_by_metric.get(metric_code, ()):
            remainder = re.sub(
                rf"\b{re.escape(alias)}[а-яё]*\b",
                " ",
                remainder,
            )
    tokens = tuple(
        token
        for token in re.sub(r"[^a-zа-яё0-9]+", " ", remainder).split()
        if len(token) > 1
        and token not in {"по", "про", "в", "на", "для", "доля", "уровень"}
    )
    return not tokens


def _number_is_in_text(value: Decimal, normalized_text: str) -> bool:
    normalized_value = format(value.normalize(), "f")
    numbers = {
        item.replace(",", ".")
        for item in re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", normalized_text)
    }
    return normalized_value in numbers or normalized_value.split(".", 1)[0] in numbers


def _subject_is_in_text(subject: str, normalized_text: str) -> bool:
    normalized_subject = _normalize(subject)
    if normalized_subject in normalized_text:
        return True
    return any(
        token in normalized_text
        for token in normalized_subject.split()
        if len(token) >= 5
    )


def _funding_is_explicit(
    value: FundingType | None, normalized_text: str
) -> bool:
    if value is None:
        return False
    markers = {
        "budget": ("бюджет", "бесплат"),
        "paid": ("платн", "коммерческ", "за деньги"),
        "targeted": ("целев"),
        "unknown": ("не знаю", "неважно"),
    }.get(value.value, ())
    return any(marker in normalized_text for marker in markers)


def _study_form_is_explicit(
    value: StudyForm | None, normalized_text: str
) -> bool:
    if value is None:
        return False
    markers = {
        "full_time": ("очн", "дневн"),
        "part_time": ("заочн",),
        "evening": ("вечерн",),
        "online": ("онлайн", "дистанцион"),
        "unknown": ("не знаю", "неважно"),
    }.get(value.value, ())
    return any(marker in normalized_text for marker in markers)


def _study_form_is_ambiguous(normalized_text: str) -> bool:
    forms = (
        ("очн", "дневн"),
        ("заочн",),
        ("вечерн",),
        ("онлайн", "дистанцион"),
    )
    return sum(
        1 for markers in forms if any(marker in normalized_text for marker in markers)
    ) > 1


def _university_scope_is_explicit(
    value: AdmissionUniversityScope | None, normalized_text: str
) -> bool:
    if value is None:
        return False
    if value.value == "any_university":
        return any(
            marker in normalized_text
            for marker in (
                "любой вуз",
                "любыми вузами",
                "любым вузам",
                "любые вузы",
                "по всем вузам",
                "все вузы",
                "все университеты",
            )
        )
    if value.value == "selected_universities":
        return any(marker in normalized_text for marker in ("конкретный вуз", "несколько вузов", "один вуз", "выбранный вуз"))
    return False


__all__ = [
    "clarification_is_grounded",
    "is_explicit_any_other_request",
    "merge_ai_interpretation",
    "safe_unverified_answer",
]
