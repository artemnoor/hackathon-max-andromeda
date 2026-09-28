"""Deterministic policy implementation used before Jev is connected."""

from __future__ import annotations

from andromeda.modules.analytics.contracts.results import AnalyticsResult
from andromeda.shared.contracts.versions import DECISION_POLICY_VERSION

from ..contracts.policy import (
    DataCapabilities,
    DecisionAction,
    DecisionPolicyResult,
)
from ..contracts.public import ConversationIntent, NextAction, QuerySession


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
    if session.next_action is NextAction.ASK_FOR_EXAMS:
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question="Какие у вас баллы по предметам ЕГЭ?",
            options=("Русский язык", "Математика", "Информатика", "Другой набор"),
            reason="Admission fit requires subject-level scores",
        )
    if session.next_action is NextAction.ASK_FOR_UNIVERSITY_SCOPE:
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
        return DecisionPolicyResult(
            action=DecisionAction.ASK_CLARIFICATION,
            question="На какой год вы планируете поступать?",
            reason="Policy applicability requires an explicit admission cycle",
        )
    if session.next_action is NextAction.ASK_FOR_METRIC:
        question = "Какой показатель сравнить: математику, программирование, AI или другой?"
    else:
        question = "Какую программу, направление или вуз нужно взять в запрос?"
    return DecisionPolicyResult(action=DecisionAction.ASK_CLARIFICATION, question=question, reason="A required query slot is missing")


__all__ = ["RuleBasedDecisionPolicy"]
