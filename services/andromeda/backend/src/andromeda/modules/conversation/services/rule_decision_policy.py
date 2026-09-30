"""Deterministic policy implementation used before Jev is connected."""

from __future__ import annotations

from andromeda.modules.analytics.contracts.results import AnalyticsResult
from andromeda.modules.entity_resolution.contracts.public import ResolutionEntityType
from andromeda.shared.contracts.versions import DECISION_POLICY_VERSION

from ..contracts.policy import (
    DataCapabilities,
    DecisionAction,
    DecisionPolicyResult,
)
from ..contracts.public import (
    AdmissionUniversityScope,
    ConversationIntent,
    ConversationSlot,
    NextAction,
    QuerySession,
)


class RuleBasedDecisionPolicy:
    version = DECISION_POLICY_VERSION

    def decide(
        self,
        session: QuerySession,
        *,
        available_actions: tuple[DecisionAction, ...] = tuple(DecisionAction),
        capabilities: DataCapabilities | None = None,
        last_result: AnalyticsResult | None = None,
    ) -> DecisionPolicyResult:
        del capabilities
        if last_result is not None and DecisionAction.SHOW_RESULT in available_actions:
            return DecisionPolicyResult(action=DecisionAction.SHOW_RESULT, reason="A typed result is already available")
        if session.next_action in {
            NextAction.ASK_FOR_EXAMS,
            NextAction.ASK_FOR_UNIVERSITY_SCOPE,
            NextAction.ASK_FOR_FUNDING,
            NextAction.ASK_FOR_STUDY_FORM,
            NextAction.ASK_FOR_ADMISSION_YEAR,
            NextAction.ASK_FOR_METRIC,
            NextAction.ASK_FOR_ENTITY,
            NextAction.CLARIFY,
        } and DecisionAction.ASK_CLARIFICATION in available_actions:
            return _clarification(session)
        if session.intent is ConversationIntent.COMPARE_PROGRAMS and DecisionAction.COMPARE in available_actions:
            return DecisionPolicyResult(action=DecisionAction.COMPARE, reason="Multiple resolved programs require comparison")
        if session.next_action is NextAction.EXECUTE_QUERY and DecisionAction.EXECUTE_QUERY in available_actions:
            return DecisionPolicyResult(action=DecisionAction.EXECUTE_QUERY, reason="All required typed slots are present")
        if DecisionAction.ASK_CLARIFICATION in available_actions:
            return DecisionPolicyResult(
                action=DecisionAction.ASK_CLARIFICATION,
                question="Уточните, что именно нужно сравнить или найти.",
                reason="The deterministic parser needs more typed information",
            )
        return DecisionPolicyResult(action=available_actions[0], reason="Fallback to the first permitted action")


def _clarification(session: QuerySession) -> DecisionPolicyResult:
    if session.intent is ConversationIntent.UNKNOWN:
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question=(
                "Опишите задачу своими словами. Если вопрос о поступлении или программах, "
                "добавьте известные вам вуз, направление или баллы."
            ),
            reason="The deterministic parser could not identify a supported intent",
        )
    if session.next_action is NextAction.ASK_FOR_EXAMS:
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question=(
                "Уточните, какие предметные баллы ЕГЭ изменились. Напишите предмет и новый результат; "
                "я сохраню остальные введённые баллы и не буду сама распределять общий балл."
                if session.known_slots.get("exam_scores_update_pending") is True
                else "Какие баллы ЕГЭ у вас есть? Укажите предмет и результат каждого экзамена."
            ),
            reason="Admission fit requires subject-level scores",
        )
    if session.next_action is NextAction.ASK_FOR_UNIVERSITY_SCOPE:
        unresolved_university = next(
            (
                item.partition(":")[2]
                for item in session.unresolved_entities
                if item.startswith("university:")
            ),
            None,
        )
        if unresolved_university:
            return DecisionPolicyResult(
                action=DecisionAction.ASK_CLARIFICATION,
                question=(
                    f"Не нашла вуз «{unresolved_university}» в доступном каталоге. "
                    "Уточните название или выберите вуз, по которому доступны данные."
                ),
                reason="The requested university is not present in the resolved catalog",
            )
        if (
            session.admission_university_scope
            is AdmissionUniversityScope.SELECTED_UNIVERSITIES
        ):
            return DecisionPolicyResult(
                action=DecisionAction.ASK_CLARIFICATION,
                question=(
                    "Напишите название одного или нескольких вузов через запятую."
                ),
                reason="A selected-university search needs one or more university names",
            )
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question="Искать по конкретному вузу, нескольким вузам или по всем?",
            options=("Конкретный вуз", "Несколько вузов", "Любые вузы"),
            reason="Admission search needs an explicit university scope",
        )
    if session.next_action is NextAction.ASK_FOR_FUNDING:
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question="Рассматривать бюджет или платное обучение?",
            options=("Бюджет", "Платное"),
            reason="Funding type materially changes admission offerings and fit",
        )
    if session.next_action is NextAction.ASK_FOR_STUDY_FORM:
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question="Уточните форму обучения: очная, заочная, вечерняя или онлайн?",
            options=("Очная", "Заочная", "Вечерняя", "Онлайн"),
            reason="The request mentions more than one study form",
        )
    if session.next_action is NextAction.ASK_FOR_ADMISSION_YEAR:
        if session.intent is ConversationIntent.OLYMPIAD_BENEFITS:
            return DecisionPolicyResult(
                action=DecisionAction.ASK_CLARIFICATION,
                question="На какой год планируете поступать? Год диплома тоже укажите, если известен.",
                reason="Olympiad rules are scoped to an admission year",
            )
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question="На какой год вы планируете поступать?",
            reason="Policy applicability requires an explicit admission cycle",
        )
    if (
        session.intent is ConversationIntent.PROGRAM_DETAILS
        and ConversationSlot.ENTITY in session.missing_slots
    ):
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question="Какую именно программу открыть? Напишите название или код программы.",
            reason="A program card needs one resolved canonical program",
        )
    if (
        session.intent is ConversationIntent.OLYMPIAD_BENEFITS
        and ConversationSlot.OLYMPIAD in session.missing_slots
    ):
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question=(
                "Напишите официальное название олимпиады. Если знаете, "
                "добавьте профиль, уровень, год диплома и год поступления."
            ),
            reason="Olympiad facts require an identifiable source-backed olympiad",
        )
    if ConversationSlot.INTERESTS in session.missing_slots:
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question=(
                "Что вам хотелось бы изучать или делать? Напишите своими словами; "
                "например, программирование, ИИ, инженерия или бизнес."
            ),
            reason="Program discovery needs at least one user-stated content preference",
        )
    if session.next_action is NextAction.ASK_FOR_METRIC:
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question="Какой показатель важен для сравнения? Напишите своими словами.",
            reason="A comparison needs a supported metric",
        )
    if (
        session.next_action is NextAction.ASK_FOR_ENTITY
        and session.intent is ConversationIntent.COMPARE_PROGRAMS
    ):
        unresolved_queries = tuple(
            item.partition(":")[2] or item for item in session.unresolved_entities
        )
        if unresolved_queries:
            query = unresolved_queries[0].replace("\n", " ").strip()[:120]
            unresolved_set = set(unresolved_queries)
            resolved_count = sum(
                1
                for entity_type in (
                    ResolutionEntityType.PROGRAM,
                    ResolutionEntityType.DIRECTION,
                )
                for entity_id in session.entities.get(entity_type, ())
                if entity_id not in unresolved_set
            )
            question = (
                f"Одну программу или направление уже нашла, но не нашла «{query}» "
                "в доступном каталоге. Уточните вуз, полное название или код направления."
                if resolved_count
                else f"Не нашла «{query}» среди доступных программ и направлений. "
                "Уточните вуз и полное название или пришлите код направления."
            )
            return DecisionPolicyResult(
                action=DecisionAction.ASK_CLARIFICATION,
                question=question,
                reason="A comparison entity could not be resolved in the available catalog",
            )
        resolved_count = sum(
            len(session.entities.get(entity_type, ()))
            for entity_type in (
                ResolutionEntityType.PROGRAM,
                ResolutionEntityType.DIRECTION,
            )
        )
        question = (
            "Первое направление или программа уже найдены. Напишите второе название."
            if resolved_count == 1
            else "Какие направления или программы сравнить? Напишите их названия, можно своими словами."
        )
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question=question,
            reason="A comparison needs at least two resolved directions or programs",
        )
    else:
        question = (
            "Какие направления или программы сравнить? Напишите их названия, можно своими словами."
            if session.intent is ConversationIntent.COMPARE_PROGRAMS
            else "Какую программу, направление или вуз нужно взять в запрос?"
        )
    return DecisionPolicyResult(action=DecisionAction.ASK_CLARIFICATION, question=question, reason="A required query slot is missing")


__all__ = ["RuleBasedDecisionPolicy"]
