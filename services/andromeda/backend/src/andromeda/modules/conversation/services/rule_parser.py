"""Small deterministic parser for the acceptance corpus.

This parser produces partial typed facts. Entity IDs are resolved later by the
backend entity-resolution ports; no natural-language text becomes SQL.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from decimal import Decimal

from andromeda.modules.admission_benefits.contracts.public import OlympiadResultType
from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.modules.analytics.contracts.metrics import MetricAggregation
from andromeda.modules.analytics.contracts.query import QueryScope
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.shared.contracts.errors import ContractError, ErrorCode

from ..contracts.public import (
    CONVERSATION_PARSER_VERSION,
    AdmissionUniversityScope,
    ConversationIntent,
    ExamScore,
    FactOrigin,
    ParsedQuery,
    PolicyQueryContext,
    PolicyQueryFocus,
    PolicyQueryYear,
)
from .program_preferences import area_is_in_text, extract_explicit_area_preferences

_METRIC_ALIASES = {
    "математик": "math_share",
    "математическая нагрузка": "math_share",
    "математике": "math_share",
    "математики": "math_share",
    "матан": "math_share",
    "программирован": "programming_share",
    "разработк": "programming_share",
    "кодинг": "programming_share",
    "искусственн интеллект": "ai_share",
    "машинн обучен": "ai_share",
    "искусственный интеллект": "ai_share",
    "машинное обучение": "ai_share",
    "ai": "ai_share",
    "физик": "physics_share",
    "бизнес": "business_share",
    "аналитик": "analytics_share",
}
_SUBJECT_ALIASES = (
    ("русский", "русский язык"),
    ("математика", "математика"),
    ("информатика", "информатика"),
    ("физика", "физика"),
    ("обществознание", "обществознание"),
    ("английский", "английский язык"),
    ("история", "история"),
    ("химия", "химия"),
    ("биология", "биология"),
    ("литература", "литература"),
    ("география", "география"),
)


class RuleBasedQueryParser:
    version = CONVERSATION_PARSER_VERSION
    max_input_length = 2000

    def parse(self, text: str) -> ParsedQuery:
        if not isinstance(text, str):
            raise ContractError(ErrorCode.INVALID_QUERY, "Query text must be a string")
        if len(text) > self.max_input_length:
            raise ContractError(
                ErrorCode.INVALID_QUERY, "Query text exceeds the supported size"
            )
        if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
            raise ContractError(
                ErrorCode.INVALID_QUERY,
                "Query text contains unsupported control characters",
            )
        cleaned = " ".join(text.split())
        if not cleaned:
            return ParsedQuery(unresolved_text="")
        normalized = cleaned.casefold().replace("ё", "е")
        olympiad_inquiry = (
            "олимпиад" in normalized
            and any(
                marker in normalized
                for marker in ("диплом", "победител", "призер", "льгот", "бви")
            )
            and not any(
                marker in normalized
                for marker in ("правил", "закон", "приказ", "измен", "вступ")
            )
        )
        policy_query_context = (
            None if olympiad_inquiry else _parse_policy_query_context(normalized)
        )
        exam_scores = _parse_exam_scores(normalized)
        total_score = _parse_total_score(normalized)
        metric_codes = _parse_metrics(normalized)
        if exam_scores and not any(
            marker in normalized
            for marker in ("где больше", "где меньше", "сравни", "по математике")
        ):
            metric_codes = ()
        university_queries, direction_queries, program_queries = (
            _parse_canonical_entities(normalized)
        )
        funding_type = _parse_funding_type(normalized)
        study_form, study_form_ambiguous = _parse_study_form(normalized)
        admission_year = _parse_admission_year(normalized)
        result_year_match = re.search(
            r"\bдиплом\w*\s+(?:за\s+)?(20\d{2})\b", normalized
        )
        olympiad_result_year = (
            int(result_year_match.group(1)) if result_year_match else None
        )
        if olympiad_inquiry and olympiad_result_year == admission_year and not re.search(
            r"\bпоступ\w*\b", normalized
        ):
            admission_year = None
        if (
            policy_query_context is not None
            and policy_query_context.mentioned_effective_year is not None
            and not _has_explicit_applicant_year(normalized)
        ):
            admission_year = None
        intent = _parse_intent(
            normalized,
            total_score,
            exam_scores,
            metric_codes,
            funding_type,
            study_form,
            admission_year,
            policy_query_context,
        )
        noisy_catalog_topic = _is_noisy_catalog_topic(normalized)
        preferred_areas, avoided_areas = extract_explicit_area_preferences(
            normalized,
            infer_from_area_mention=(
                intent is ConversationIntent.PROGRAM_DISCOVERY
                or (
                    noisy_catalog_topic
                    and intent
                    in {
                        ConversationIntent.UNKNOWN,
                        ConversationIntent.ANALYTICS_QUERY,
                    }
                )
            ),
        )
        if olympiad_inquiry:
            intent = ConversationIntent.OLYMPIAD_BENEFITS
        if noisy_catalog_topic and intent in {
            ConversationIntent.UNKNOWN,
            ConversationIntent.ANALYTICS_QUERY,
        }:
            intent = ConversationIntent.PROGRAM_DISCOVERY
        if (
            (preferred_areas or avoided_areas)
            and intent in {ConversationIntent.UNKNOWN, ConversationIntent.ANALYTICS_QUERY}
        ):
            intent = ConversationIntent.PROGRAM_DISCOVERY
        aggregation = MetricAggregation.MEAN if "в среднем" in normalized else None
        scope = (
            QueryScope.UNIVERSITY
            if "вуз" in normalized or "университет" in normalized
            else None
        )
        return ParsedQuery(
            intent=intent,
            olympiad_query=(
                match.group(1).strip()
                if (match := re.search(r"\bолимпиад\w*\s+[«\"]([^»\"]+)[»\"]", normalized))
                else None
            ),
            olympiad_profile_query=(
                match.group(1).strip()
                if (match := re.search(r"\bпрофил\w*\s+[«\"]([^»\"]+)[»\"]", normalized))
                else None
            ),
            olympiad_result_year=olympiad_result_year,
            olympiad_level=(
                int(match.group(1))
                if (match := re.search(r"\b([123])\s*(?:-?го|ого)?\s*уровн\w*\b", normalized))
                else None
            ),
            olympiad_result_type=(
                OlympiadResultType.WINNER
                if "победител" in normalized
                else OlympiadResultType.PRIZE_WINNER
                if "призер" in normalized
                else None
            ),
            admission_university_scope=_parse_admission_university_scope(normalized),
            metric_codes=metric_codes,
            university_queries=university_queries,
            direction_queries=direction_queries,
            program_queries=program_queries,
            total_score=total_score,
            exam_scores=exam_scores,
            preferred_areas=preferred_areas,
            avoided_areas=avoided_areas,
            funding_type=funding_type,
            study_form=study_form,
            study_form_ambiguous=study_form_ambiguous,
            admission_year=admission_year,
            policy_query_context=policy_query_context,
            aggregation=aggregation,
            scope=scope,
            semester=_parse_semester(normalized),
            course_year=_parse_course_year(normalized),
            unresolved_text=cleaned[:1000],
        )


def _parse_policy_query_context(text: str) -> PolicyQueryContext | None:
    applicability_markers = (
        "касает",
        "влияет ли на меня",
        "относится ко мне",
        "меня затронет",
        "кого касается",
    )
    impact_markers = (
        "шанс",
        "конкурсн",
        "маршрут поступлен",
        "что мне изменить",
        "нужно ли что-то делать",
        "для меня",
        "мои результаты",
        "моя подача",
    )
    history_markers = (
        "чем правил",
        "что изменилось",
        "что действовало",
        "вчера отвечал",
        "на дату",
        "как было",
        "истори",
    )
    change_markers = (
        "правда ли",
        "говорят",
        "слух",
        "новост",
        "измен",
        "введ",
        "вступ",
        "принят",
        "обсужда",
        "проект",
        "приказ",
        "постановлен",
        "закон",
        "отмен",
        "исключен",
        "с какого года",
        "официально",
    )
    status_markers = ("действует ли", "какой статус", "уже действует", "уже принято")
    what_if_markers = ("что если", "а если", "предположим", "если все-таки примут")
    policy_topic_markers = (
        "правил", "норм", "закон", "приказ", "постановлен", "егэ", "экзамен",
        "бви", "олимпиад", "квот", "льгот", "достижен", "вузовск",
    )
    what_if_policy = any(marker in text for marker in what_if_markers) and any(
        marker in text for marker in policy_topic_markers
    )
    is_policy_comparison = any(marker in text for marker in ("сравн", "отлич")) and any(
        marker in text
        for marker in (
            "правил",
            "закон",
            "приказ",
            "постановлен",
            "егэ",
            "бви",
            "олимпиад",
            "квот",
            "индивидуальн достижен",
        )
    )
    is_historical_knowledge_query = (
        "вчера" in text
        and "знал" in text
        and any(marker in text for marker in ("andromeda", "система"))
    )
    is_fourth_exam = any(
        value in text for value in ("четверт", "4-й егэ", "4 егэ")
    ) and any(value in text for value in ("егэ", "экзамен"))
    is_policy_question = (
        any(
            marker in text
            for marker in (
                applicability_markers
                + impact_markers
                + history_markers
                + change_markers
                + status_markers
            )
        )
        or is_policy_comparison
        or is_historical_knowledge_query
        or what_if_policy
        or (
            is_fourth_exam
            and any(
                value in text
                for value in ("будет", "введ", "говорят", "правда", "обсужда")
            )
        )
    )
    if not is_policy_question:
        return None

    if what_if_policy:
        focus = PolicyQueryFocus.WHAT_IF
    elif (
        any(marker in text for marker in history_markers)
        or is_policy_comparison
        or is_historical_knowledge_query
    ):
        focus = PolicyQueryFocus.HISTORY
    elif any(marker in text for marker in applicability_markers):
        focus = (
            PolicyQueryFocus.IMPACT
            if any(marker in text for marker in impact_markers)
            else PolicyQueryFocus.APPLICABILITY
        )
    elif any(marker in text for marker in impact_markers):
        focus = PolicyQueryFocus.IMPACT
    elif any(marker in text for marker in change_markers):
        focus = PolicyQueryFocus.CHANGE
    else:
        focus = PolicyQueryFocus.STATUS

    as_known_at = _parse_policy_as_known_at(text)
    years = (
        _parse_policy_year_mentions(text)
        if focus is PolicyQueryFocus.HISTORY
        else _parse_policy_effective_years(text)
    )
    comparison_years = (
        (years[0], years[1])
        if focus is PolicyQueryFocus.HISTORY and len(years) == 2
        else ()
    )
    mentioned_year = (
        PolicyQueryYear(year=years[0], origin=FactOrigin.EXPLICIT_USER, confirmed=True)
        if len(years) == 1
        else None
    )
    return PolicyQueryContext(
        focus=focus,
        claim_predicate=_parse_policy_claim_predicate(text),
        mentioned_effective_year=mentioned_year,
        comparison_admission_years=comparison_years,
        valid_as_of=_parse_policy_as_of(text) if as_known_at is None else None,
        as_known_at=as_known_at,
    )


def _parse_policy_claim_predicate(text: str) -> str | None:
    if any(token in text for token in ("четверт", "4-й", "4 егэ")) and any(
        token in text for token in ("егэ", "экзамен")
    ):
        return "admission.exam.required_count"
    if "бви" in text or "без вступительных" in text:
        return "admission_benefit.bvi"
    if "100 балл" in text and any(token in text for token in ("олимпиад", "профил")):
        return "admission_benefit.olympiad_100_points"
    if "индивидуальн" in text and "достижен" in text:
        return "admission.individual_achievement"
    return None


def _parse_policy_as_of(text: str) -> datetime | None:
    match = re.search(
        r"\b(?:на дату|по состоянию на)\s*(20\d{2}-\d{2}-\d{2})\b",
        text,
    )
    if match is None:
        return None
    try:
        return datetime.fromisoformat(match.group(1)).replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_policy_as_known_at(text: str) -> datetime | None:
    if not any(
        marker in text
        for marker in (
            "что знала andromeda",
            "что знала система",
            "что было известно системе",
            "что было известно andromeda",
            "знания andromeda",
        )
    ):
        return None
    match = re.search(r"\b(?:на дату|по состоянию на)\s*(20\d{2}-\d{2}-\d{2})\b", text)
    if match is None:
        return None
    try:
        day = date.fromisoformat(match.group(1))
        # Date-only as-of values include the full UTC calendar date.
        return datetime.combine(day, time.max, tzinfo=UTC)
    except ValueError:
        return None


def _parse_policy_year_mentions(text: str) -> tuple[int, ...]:
    years = {
        int(value)
        for value in re.findall(r"(?<![\d-])(?:19|20|21)\d{2}(?![\d-])", text)
    }
    return tuple(sorted(years))[:2]


def _parse_policy_effective_years(text: str) -> tuple[int, ...]:
    patterns = (
        r"\b(?:с|со)\s*(20\d{2})\b",
        r"\b(20\d{2})\s*(?:году|год|г\.)\s*.{0,40}\b(?:введ|начнет|начнут|вступ|действ)\w*",
        r"\b(?:введ|начнет|начнут|вступ|действ)\w*.{0,40}\b(20\d{2})\b",
    )
    years = {int(match) for pattern in patterns for match in re.findall(pattern, text)}
    return tuple(sorted(years))


def _has_explicit_applicant_year(text: str) -> bool:
    return bool(
        re.search(
            r"(?:поступ\w*|при[её]м\w*|кампан\w*|набор\w*).{0,32}20\d{2}"
            r"|20\d{2}.{0,32}(?:поступ\w*|при[её]м\w*|кампан\w*|набор\w*)",
            text,
        )
    )


def _parse_admission_university_scope(text: str) -> AdmissionUniversityScope | None:
    any_university_phrases = (
        "любые вузы",
        "любой вуз",
        "по всем вузам",
        "все вузы",
        "в любом вузе",
        "любые университеты",
        "любой университет",
        "все университеты",
        "в любом университете",
    )
    if any(phrase in text for phrase in any_university_phrases):
        return AdmissionUniversityScope.ANY_UNIVERSITY
    selected_university_phrases = (
        "конкретный вуз",
        "конкретному вузу",
        "один вуз",
        "несколько вузов",
        "нескольким вузам",
    )
    if any(phrase in text for phrase in selected_university_phrases):
        return AdmissionUniversityScope.SELECTED_UNIVERSITIES
    return None


def _parse_intent(
    text: str,
    total_score: Decimal | None,
    exam_scores: tuple[ExamScore, ...],
    metrics: tuple[str, ...],
    funding_type: FundingType | None,
    study_form: StudyForm | None,
    admission_year: int | None,
    policy_query_context: PolicyQueryContext | None,
) -> ConversationIntent:
    if policy_query_context is not None:
        return ConversationIntent.KNOWLEDGE_POLICY_QUERY
    admission_words = (
        "куда",
        "прохожу",
        "поступ",
        "егэ",
        "бюджет",
        "платн",
        "проходной",
    )
    if any(
        marker in text
        for marker in (
            "где лучше",
            "похож",
            "сравни эти две программы",
            "сравни эти программы",
        )
    ):
        return ConversationIntent.ANALYTICS_QUERY
    compare_words = (
        "сравни",
        "сравнить",
        "между",
        " vs ",
        "versus",
    )
    if any(word in text for word in compare_words):
        return ConversationIntent.COMPARE_PROGRAMS
    if _has_natural_comparison_wording(text):
        return ConversationIntent.COMPARE_PROGRAMS
    asks_for_curriculum = re.search(
        r"\b(?:учебн\w*\s+план\w*|дисциплин\w*|предмет\w*|"
        r"час\w*|зет|курс\w*)\b",
        text,
    ) and re.search(r"\b(?:расскаж\w*|покаж\w*|каки\w*|что|сколько)\b", text)
    asks_for_card = re.search(
        r"\bрасскаж\w*\b.{0,80}\bпрограмм\w*\b", text
    )
    if (asks_for_curriculum or asks_for_card) and not any(
        word in text for word in admission_words
    ):
        return ConversationIntent.PROGRAM_DETAILS
    discovery_words = (
        "подбери",
        "подобрать",
        "что есть по",
        "найди программу",
        "найди программы",
        "программы связаны",
        "программы по направлению",
        "программы по специальности",
        "не знаю что выбрать",
        "не понимаю куда",
        "хочу в айти",
        "хочу в it",
        "интересует программ",
        "нравится программ",
        "хочу изучать",
    )
    discovery_action = re.search(
        r"\b(?:покаж\w*|найд\w*|подбер\w*|посовет\w*|подскаж\w*|ищ\w*)\b"
        r".{0,64}\b(?:программ\w*|направлен\w*|специальност\w*)\b",
        text,
    ) is not None
    if (any(marker in text for marker in discovery_words) or discovery_action) and not (
        total_score is not None
        or exam_scores
        or funding_type is not None
        or admission_year is not None
        or any(marker in text for marker in ("шансы", "проходной балл", "баллы егэ"))
    ):
        return ConversationIntent.PROGRAM_DISCOVERY
    if (
        total_score is not None
        or exam_scores
        or funding_type is not None
        or study_form is not None
        or admission_year is not None
        or any(word in text for word in admission_words)
    ):
        return ConversationIntent.ADMISSION_SEARCH
    if metrics or any(
        word in text
        for word in (
            "где больше",
            "где меньше",
            "где лучше",
            "похож",
            "топ",
            "покажи программы",
        )
    ):
        return ConversationIntent.ANALYTICS_QUERY
    return ConversationIntent.UNKNOWN


def _has_natural_comparison_wording(text: str) -> bool:
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bчем\b.{0,160}\bотлич\w*\b",
            r"\bв\s+ч[её]м\s+разниц\w*\s+между\b",
            r"\bразниц\w*\s+между\b",
            r"\bчто\s+общего\s+(?:между|у)\b",
        )
    )


def _parse_funding_type(text: str) -> FundingType | None:
    budget = bool(re.search(r"\bбюджет\w*\b", text))
    paid = bool(re.search(r"\b(?:платн\w*|коммерческ\w*|за деньги)\b", text))
    if budget == paid:
        return None
    return FundingType.BUDGET if budget else FundingType.PAID


def _parse_study_form(text: str) -> tuple[StudyForm | None, bool]:
    matches: set[StudyForm] = set()
    if re.search(r"\b(?:очн\w*|дневн\w*)\b", text):
        matches.add(StudyForm.FULL_TIME)
    if re.search(r"\bзаочн\w*\b", text):
        matches.add(StudyForm.PART_TIME)
    if re.search(r"\bвечерн\w*\b", text):
        matches.add(StudyForm.EVENING)
    if re.search(r"\b(?:дистанционн\w*|онлайн)\b", text):
        matches.add(StudyForm.ONLINE)
    if len(matches) > 1:
        return None, True
    return (next(iter(matches)), False) if matches else (None, False)


def _parse_admission_year(text: str) -> int | None:
    patterns = (
        r"(?:при[её]м\w*|поступлен\w*|кампан\w*|набор\w*)\s*(?:на|в)?\s*(20\d{2})",
        r"\b(?:на|в)\s*(20\d{2})\s*(?:году|год|г\.)",
    )
    years = {int(match) for pattern in patterns for match in re.findall(pattern, text)}
    return next(iter(years)) if len(years) == 1 else None


def _parse_total_score(text: str) -> Decimal | None:
    match = re.search(r"\b(?:с|набра(?:л|ла|ли))\s*(\d{2,3})\b", text)
    return Decimal(match.group(1)) if match else None


def _parse_exam_scores(text: str) -> tuple[ExamScore, ...]:
    scores: list[ExamScore] = []
    for alias, subject in _SUBJECT_ALIASES:
        match = re.search(
            rf"\b{re.escape(alias)}\b\s*(?:егэ\s*)?(?:[:=-]\s*|\s+)(\d{{1,3}})\b", text
        )
        if match:
            score = Decimal(match.group(1))
            if score <= Decimal(100):
                scores.append(ExamScore(subject=subject, score=score))
    return tuple(scores)


def _parse_metrics(text: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            code
            for alias, code in _METRIC_ALIASES.items()
            if alias in text
            and not (
                code == "business_share"
                and re.search(r"\bбизнес[- ]информатик", text)
            )
        )
    )


def remove_entity_name_metrics(
    text: str,
    metric_codes: tuple[str, ...],
    entity_phrases: tuple[str, ...],
) -> tuple[str, ...]:
    """Drop metric keywords that occur only inside resolved entity names.

    Program titles often contain words such as "искусственный интеллект" or
    "математика". Those words are not a comparison criterion unless the user
    mentions them separately (for example, "сравни A и B по математике").
    """

    normalized = " ".join(text.casefold().replace("ё", "е").split())
    entity_ranges: list[tuple[int, int]] = []
    for phrase in entity_phrases:
        normalized_phrase = " ".join(phrase.casefold().replace("ё", "е").split())
        if not normalized_phrase:
            continue
        offset = 0
        while (start := normalized.find(normalized_phrase, offset)) >= 0:
            entity_ranges.append((start, start + len(normalized_phrase)))
            offset = start + len(normalized_phrase)

    if not entity_ranges:
        return metric_codes

    result: list[str] = []
    for code in metric_codes:
        aliases = tuple(alias for alias, alias_code in _METRIC_ALIASES.items() if alias_code == code)
        matches = tuple(
            (match.start(), match.end())
            for alias in aliases
            for match in re.finditer(re.escape(alias), normalized)
        )
        if not matches:
            result.append(code)
            continue
        all_mentions_are_entity_names = all(
            any(start <= match_start and match_end <= end for start, end in entity_ranges)
            for match_start, match_end in matches
        )
        if not all_mentions_are_entity_names:
            result.append(code)
    return tuple(result)


def _parse_canonical_entities(
    text: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    universities = list(re.findall(r"\buniversity:[a-z0-9-]+\b", text))
    if "бауман" in text:
        universities.append("бауманка")
    universities.extend(
        alias for alias in ("мгту", "вшэ", "hse", "мифи", "мфти", "физтех") if alias in text
    )
    if re.search(r"\bвысш\w*\s+школ\w*\s+экономик\w*\b", text):
        universities.append("высшая школа экономики")
    universities = list(dict.fromkeys(universities))
    directions = list(
        re.findall(r"\bdirection:[a-z0-9-]+:[0-9]{2}\.[0-9]{2}\.[0-9]{2}\b", text)
    )
    directions.extend(
        code for code in re.findall(r"\b[0-9]{2}\.[0-9]{2}\.[0-9]{2}\b", text)
    )
    if "прикладн" in text and "информат" in text:
        directions.append("прикладная информатика")
    if "вычислительн" in text and "техник" in text:
        directions.append("информатика и вычислительная техника")
    directions = list(dict.fromkeys(directions))
    canonical_programs = re.findall(
        r"\bprogram:[a-z0-9-]+:[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}\b", text
    )
    program_codes = re.findall(
        r"\b[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}\b", text
    )
    programs = tuple(
        dict.fromkeys(
            canonical_programs
            + [
                code for code in program_codes
                if not any(program.endswith(":" + code) for program in canonical_programs)
            ]
        )
    )
    return tuple(universities), tuple(directions), programs


def _is_noisy_catalog_topic(text: str) -> bool:
    words = tuple(re.findall(r"[a-zа-яё]+", text))
    has_program_target = any(
        word.startswith(("программ", "прогр", "направлен", "специальност"))
        for word in words
    )
    has_relation = any(
        marker in text
        for marker in (
            "связан", " по ", "около", "в области", "нрав", "интерес",
            "хочу", "не хочу", "меньше", "поменьше",
        )
    )
    has_known_area = any(area_is_in_text(area, text) for area in DisciplineAreaCode)
    has_explicit_comparison = any(
        marker in text
        for marker in (
            "сравни", "сравнить", "какая из них", "какой из них",
            "где больше", "где меньше",
        )
    )
    return has_program_target and has_relation and has_known_area and not has_explicit_comparison


def _parse_semester(text: str) -> int | None:
    match = re.search(
        r"\b(?:семестр|семестре|семестра)\s*(?:№\s*)?(1[0-2]|[1-9])\b", text
    )
    return int(match.group(1)) if match else None


def _parse_course_year(text: str) -> int | None:
    match = re.search(
        r"\b(?:курс|курсе|курса)\s*(1[0-2]|[1-9])\b|\b(1[0-2]|[1-9])\s*(?:курс|курсе|курса)\b",
        text,
    )
    if match:
        return int(match.group(1) or match.group(2))
    ordinals = ("перв", "втор", "трет", "четверт", "пят", "шест")
    for course_year, stem in enumerate(ordinals, start=1):
        if re.search(rf"\b{stem}\w*\s+курс\w*\b", text):
            return course_year
    return None


__all__ = ["RuleBasedQueryParser", "remove_entity_name_metrics"]
