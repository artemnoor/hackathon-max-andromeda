"""Deterministic knowledge rendering with an optional bounded layout planner."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

from andromeda.modules.presentation.contracts.knowledge_response import (
    KnowledgeResponseSection,
    ResolutionExplanation,
    ResponseActionability,
    ResponseClaimStage,
    ResponseCycleComparison,
    ResponseDiffStatus,
    ResponseMode,
    ResponseResolutionState,
    ResponseScopeKind,
    ResponseSourceReliability,
    ResponseUncertainty,
    RuleDisposition,
)
from andromeda.modules.presentation.contracts.verbalization import (
    KnowledgeResponseRenderResult,
    PresentationSectionKind,
    PresentationSectionRef,
    ResponseVerbalizationPlan,
    ResponseVerbalizationRequest,
    ResponseVerbalizerPort,
)

logger = logging.getLogger("andromeda.presentation.knowledge")


class KnowledgeResponseRenderer:
    """Render verified content; an optional port only orders safe section references."""

    def __init__(self, verbalizer: ResponseVerbalizerPort | None = None) -> None:
        self._verbalizer = verbalizer

    def render(
        self,
        response: KnowledgeResponseSection,
        *,
        unverified_fallback: bool = False,
    ) -> KnowledgeResponseRenderResult:
        if unverified_fallback and response.status.value != "outside_coverage":
            raise ValueError("unverified fallback is restricted to outside coverage")
        blocks = _render_blocks(response, unverified_fallback=unverified_fallback)
        if not blocks:
            return KnowledgeResponseRenderResult(
                text="Проверяемый результат пока недоступен."
            )

        ordered_ids = tuple(blocks)
        mode = ResponseMode.DETERMINISTIC
        if self._verbalizer is not None and not unverified_fallback:
            request = _verbalization_request(blocks)
            try:
                plan = self._verbalizer.plan(request)
                ordered_ids = _validated_order(plan, request)
                mode = ResponseMode.SOURCE_BACKED_VERBALIZATION
            except Exception as error:  # noqa: BLE001 - optional port must fail closed
                logger.warning(
                    "knowledge_response_verbalizer_fallback error_type=%s",
                    type(error).__name__,
                )
        text = _bounded_text(
            "\n\n".join(blocks[section_id][1] for section_id in ordered_ids)
        )
        if unverified_fallback:
            mode = ResponseMode.UNVERIFIED_FALLBACK
        return KnowledgeResponseRenderResult(text=text, response_mode=mode)


def _render_blocks(
    response: KnowledgeResponseSection,
    *,
    unverified_fallback: bool = False,
) -> dict[str, tuple[PresentationSectionRef, str]]:
    blocks: dict[str, tuple[PresentationSectionRef, str]] = {}

    def add(kind: PresentationSectionKind, seed: object, text: str) -> None:
        canonical = json.dumps(
            seed, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        section_id = (
            "section:"
            + hashlib.sha256(f"{kind.value}:{canonical}".encode()).hexdigest()
        )
        blocks[section_id] = (
            PresentationSectionRef(section_id=section_id, kind=kind),
            text,
        )

    add(
        PresentationSectionKind.STATUS,
        {
            "status": response.status.value,
            "actionability": response.actionability.value,
            "uncertainties": [item.value for item in response.uncertainties],
        },
        _status_text(response, unverified_fallback=unverified_fallback),
    )
    if response.source_assertions:
        add(
            PresentationSectionKind.SOURCE_ASSERTIONS,
            [item.model_dump(mode="json") for item in response.source_assertions],
            _source_assertions_text(response),
        )
    if response.known_facts:
        add(
            PresentationSectionKind.FACTS,
            [item.model_dump(mode="json") for item in response.known_facts],
            _facts_text(response),
        )
    if response.resolution is not None:
        add(
            PresentationSectionKind.RESOLUTION,
            response.resolution.model_dump(mode="json"),
            _resolution_text(response),
        )
    if response.cycle_comparison is not None:
        add(
            PresentationSectionKind.CYCLE_COMPARISON,
            response.cycle_comparison.model_dump(mode="json"),
            _cycle_comparison_text(response.cycle_comparison),
        )
    if response.affected_scope:
        add(
            PresentationSectionKind.SCOPE,
            [item.model_dump(mode="json") for item in response.affected_scope],
            _scope_text(response),
        )
    if response.exceptions:
        add(
            PresentationSectionKind.EXCEPTIONS,
            [item.model_dump(mode="json") for item in response.exceptions],
            _exceptions_text(response),
        )
    if response.impact_delta:
        add(
            PresentationSectionKind.IMPACT,
            [item.model_dump(mode="json") for item in response.impact_delta],
            _impact_text(response),
        )
    if response.uncertainties or response.missing_data:
        add(
            PresentationSectionKind.UNCERTAINTY,
            {
                "uncertainties": [item.value for item in response.uncertainties],
                "missing_data": response.missing_data,
            },
            _uncertainty_text(response),
        )
    if response.evidence:
        add(
            PresentationSectionKind.EVIDENCE,
            [item.model_dump(mode="json") for item in response.evidence],
            _evidence_text(response),
        )
    return blocks


def _verbalization_request(
    blocks: dict[str, tuple[PresentationSectionRef, str]],
) -> ResponseVerbalizationRequest:
    refs = tuple(item[0] for item in blocks.values())
    evidence = next(
        (
            item.section_id
            for item in refs
            if item.kind is PresentationSectionKind.EVIDENCE
        ),
        None,
    )
    return ResponseVerbalizationRequest(
        sections=refs,
        fixed_first_section=refs[0].section_id,
        fixed_last_section=evidence,
    )


def _validated_order(
    plan: ResponseVerbalizationPlan,
    request: ResponseVerbalizationRequest,
) -> tuple[str, ...]:
    if not isinstance(plan, ResponseVerbalizationPlan):
        raise TypeError("verbalizer returned an untyped presentation plan")
    expected = {item.section_id for item in request.sections}
    actual = plan.section_order
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError(
            "verbalizer must preserve every permitted response section exactly once"
        )
    if actual[0] != request.fixed_first_section:
        raise ValueError("verbalizer cannot move the status section")
    if (
        request.fixed_last_section is not None
        and actual[-1] != request.fixed_last_section
    ):
        raise ValueError("verbalizer cannot move the evidence section")
    return actual


def _status_text(
    response: KnowledgeResponseSection,
    *,
    unverified_fallback: bool = False,
) -> str:
    labels = {
        "source_assertion": "Найдено утверждение источника; оно само по себе не подтверждает действующее правило.",
        "policy_resolved": "Для заданного контекста найден применимый набор правил.",
        "conflict": "Источники или правила расходятся; однозначный вывод не сделан.",
        "no_evidence": "Утверждение по распознанной теме не найдено; отсутствие данных не доказывает отсутствие правила.",
        "insufficient_data": "Для однозначного вывода не хватает проверенных данных.",
        "outside_coverage": "Эта тема пока вне структурированного охвата Andromeda.",
        "historical_state_unavailable": "Историческое состояние знаний на указанную дату восстановить нельзя.",
        "review_required": "Найденная информация требует проверки.",
        "uncertain": "Проверенные данные пока не позволяют сделать однозначный вывод.",
    }
    actionability = {
        ResponseActionability.NOT_APPLICABLE: "не относится к указанному контексту",
        ResponseActionability.FUTURE_ONLY: "касается только будущего периода",
        ResponseActionability.INFORMATIONAL: "информация для учёта",
        ResponseActionability.ACTION_RECOMMENDED: "рекомендуется проверить дальнейшие действия",
        ResponseActionability.ACTION_REQUIRED: "требуется действие",
        ResponseActionability.UNCERTAIN: "применимость пока не определена",
        ResponseActionability.BLOCKED_BY_MISSING_DATA: "не хватает данных для проверки применимости",
    }
    lines = [
        f"Статус: {labels[response.status.value]}",
        f"Для пользователя: {actionability[response.actionability]}",
    ]
    if unverified_fallback:
        lines.insert(
            0, "Режим: вне проверенного покрытия, общий ответ не предоставлен."
        )
    if response.as_known_at is not None:
        lines.append(f"Состояние знаний на: {_date_label(response.as_known_at)}.")
    if response.last_checked is not None:
        lines.append(f"Источник зафиксирован: {_date_label(response.last_checked)}.")
    return "\n".join(lines)


def _source_assertions_text(response: KnowledgeResponseSection) -> str:
    lines = ["Что сообщают источники:"]
    for item in response.source_assertions:
        stage = _claim_stage_label(item.stage)
        reliability = _reliability_label(item.reliability)
        excerpt = _bounded_excerpt(item.assertion, 600)
        lines.append(f"• {item.source_name} ({reliability}; {stage}): «{excerpt}»")
        if item.asserted_value is not None:
            fact = item.asserted_value
            subject = f" для {fact.subject_label}" if fact.subject_label else ""
            unit = f" {fact.unit}" if fact.unit else ""
            lines.append(
                f"  Структурированное утверждение{subject}: {fact.label} — {fact.value}{unit}."
            )
        dates = _claim_dates(
            item.published_at, item.adopted_at, item.effective_from, item.effective_to
        )
        if dates:
            lines.append(f"  Даты источника: {dates}.")
    return "\n".join(lines)


def _resolution_text(response: KnowledgeResponseSection) -> str:
    assert response.resolution is not None
    explanation = response.resolution
    selected = len(explanation.selected_rules)
    considered = len(explanation.considered_rules)
    state_label = {
        ResponseResolutionState.RESOLVED: "резолвер выбрал применимые редакции",
        ResponseResolutionState.CONFLICT: "обнаружен конфликт",
        ResponseResolutionState.NO_MATCH: "применимая редакция не найдена",
        ResponseResolutionState.BLOCKED: "проверка остановлена из-за недостающих данных",
        ResponseResolutionState.INDETERMINATE: "результат неопределён",
        ResponseResolutionState.CANDIDATES: "остались кандидаты для разбора",
    }[explanation.state]
    lines = [
        f"Проверка правил: {state_label}; выбрано {selected}, рассмотрено {considered}."
    ]
    if explanation.valid_as_of is not None:
        lines.append(
            f"Проверено для даты действия: {_date_label(explanation.valid_as_of)}."
        )
    counts: dict[RuleDisposition, int] = {}
    for item in explanation.considered_rules:
        counts[item.disposition] = counts.get(item.disposition, 0) + 1
    rejected = [
        f"{count} {_disposition_label(disposition)}"
        for disposition, count in sorted(counts.items(), key=lambda pair: pair[0].value)
        if disposition is not RuleDisposition.SELECTED
    ]
    if rejected:
        lines.append("Остальные редакции: " + ", ".join(rejected) + ".")
    return "\n".join(lines)


def _scope_text(response: KnowledgeResponseSection) -> str:
    labels = {
        ResponseScopeKind.FEDERAL: "федеральный уровень",
        ResponseScopeKind.UNIVERSITY: "вуз",
        ResponseScopeKind.DIRECTION: "направление",
        ResponseScopeKind.PROGRAM: "программа",
        ResponseScopeKind.ADMISSION_ROUTE: "маршрут поступления",
        ResponseScopeKind.OTHER: "другая область",
    }
    values = tuple(
        f"{labels[item.scope_kind]} ({item.scope_reference})"
        if item.scope_reference
        else labels[item.scope_kind]
        for item in response.affected_scope[:20]
    )
    suffix = (
        f" Ещё областей: {len(response.affected_scope) - len(values)}."
        if len(response.affected_scope) > len(values)
        else ""
    )
    return "Кого касается выбранное правило: " + "; ".join(values) + "." + suffix


def _cycle_comparison_text(comparison: ResponseCycleComparison) -> str:
    def summary(year: int, explanation: ResolutionExplanation) -> str:
        selected = explanation.selected_rules
        state = explanation.state
        if selected:
            rules = ", ".join(
                f"{item.rule_reference} (редакция {item.revision})"
                for item in selected[:8]
            )
            extra = f" и ещё {len(selected) - 8}" if len(selected) > 8 else ""
            return f"{year}: выбрано {rules}{extra}"
        return f"{year}: {_resolution_state_label(state)}"

    lines = [
        "Сравнение правил для приёмных кампаний:",
        summary(comparison.before_admission_year, comparison.before_resolution),
        summary(comparison.after_admission_year, comparison.after_resolution),
    ]
    if comparison.diff_status is ResponseDiffStatus.COMPLETE:
        lines.append(f"Структурированных изменений: {len(comparison.changes)}.")
        for item in comparison.changes[:8]:
            before = _bounded_excerpt(item.before, 240) if item.before else "нет"
            after = _bounded_excerpt(item.after, 240) if item.after else "нет"
            lines.append(f"• {item.path}: {before} → {after}.")
        if len(comparison.changes) > 8:
            lines.append(f"Других изменений: {len(comparison.changes) - 8}.")
    else:
        lines.append(
            "Сравнение неполное или неоднозначное; однозначный diff недоступен."
        )
    return "\n".join(lines)


def _resolution_state_label(state: ResponseResolutionState) -> str:
    labels = {
        ResponseResolutionState.RESOLVED: "применимое правило определено",
        ResponseResolutionState.CONFLICT: "обнаружен конфликт",
        ResponseResolutionState.NO_MATCH: "правило не найдено в доступных данных",
        ResponseResolutionState.BLOCKED: "не хватает данных для проверки",
        ResponseResolutionState.INDETERMINATE: "результат неопределён",
        ResponseResolutionState.CANDIDATES: "остались кандидаты для разбора",
    }
    return labels[state]


def _exceptions_text(response: KnowledgeResponseSection) -> str:
    lines = ["Исключения и override:"]
    for item in response.exceptions[:20]:
        chosen = (
            f"; выбранная редакция {item.selected_rule.rule_reference}"
            if item.selected_rule is not None
            else "; итоговый выбор не установлен"
        )
        rules = ", ".join(rule.rule_reference for rule in item.rules)
        lines.append(f"• Связаны редакции {rules}{chosen}.")
    if len(response.exceptions) > len(lines) - 1:
        lines.append(f"Ещё исключений: {len(response.exceptions) - (len(lines) - 1)}.")
    return "\n".join(lines)


def _impact_text(response: KnowledgeResponseSection) -> str:
    lines = [
        "Что меняется: "
        + "; ".join(
            f"{item.label}: {item.value}{f' {item.unit}' if item.unit else ''}"
            for item in response.impact_delta[:20]
        )
        + "."
    ]
    if len(response.impact_delta) > 20:
        lines.append(f"Ещё изменений: {len(response.impact_delta) - 20}.")
    return "\n".join(lines)


def _facts_text(response: KnowledgeResponseSection) -> str:
    lines = ["Что известно:"]
    for item in response.known_facts[:20]:
        subject = f" ({item.subject_label})" if item.subject_label else ""
        unit = f" {item.unit}" if item.unit else ""
        lines.append(f"• {item.label}{subject}: {item.value}{unit}.")
    if len(response.known_facts) > 20:
        lines.append(f"Ещё фактов: {len(response.known_facts) - 20}.")
    return "\n".join(lines)


def _uncertainty_text(response: KnowledgeResponseSection) -> str:
    labels = {
        ResponseUncertainty.NO_SOURCE_ASSERTION_FOUND: "не найдено source-backed утверждение",
        ResponseUncertainty.SOURCE_ASSERTION_NEEDS_REVIEW: "утверждение требует проверки",
        ResponseUncertainty.SOURCE_ASSERTIONS_DISAGREE: "утверждения расходятся",
        ResponseUncertainty.EFFECTIVE_DATE_UNKNOWN: "дата вступления в силу неизвестна",
        ResponseUncertainty.SCOPE_UNKNOWN: "область действия неизвестна",
        ResponseUncertainty.DOMAIN_RESULT_UNAVAILABLE: "domain-модуль ещё не рассчитал результат",
        ResponseUncertainty.POLICY_CONFLICT_UNRESOLVED: "конфликт правил не разрешён",
        ResponseUncertainty.OUTSIDE_KNOWLEDGE_COVERAGE: "тема вне текущего охвата знаний",
        ResponseUncertainty.EVIDENCE_UNAVAILABLE: "исходный документ сейчас недоступен",
        ResponseUncertainty.HISTORICAL_STATE_UNAVAILABLE: "историческое состояние на эту дату не сохранено или не восстановимо",
    }
    values = [labels[item] for item in response.uncertainties]
    if response.missing_data:
        values.extend(_missing_data_label(item) for item in response.missing_data)
    return "Что пока неизвестно: " + "; ".join(values) + "."


def _evidence_text(response: KnowledgeResponseSection) -> str:
    lines = ["Источники и фрагменты:"]
    for item in response.evidence[:20]:
        name = item.source_name or "Источник"
        locator = _locator_label(
            item.locator.page,
            item.locator.section,
            item.locator.table,
            item.locator.row,
        )
        captured = _date_label(item.captured_at)
        details = ", ".join(value for value in (locator, captured) if value)
        lines.append(f"• {name}{f' — {details}' if details else ''}.")
    if len(response.evidence) > 20:
        lines.append(
            f"Дополнительных ссылок в структурированных данных: {len(response.evidence) - 20}."
        )
    return "\n".join(lines)


def _claim_stage_label(stage: ResponseClaimStage) -> str:
    return {
        ResponseClaimStage.POSSIBLE: "слух или гипотеза",
        ResponseClaimStage.ANNOUNCED: "объявлено",
        ResponseClaimStage.PROPOSAL: "предложение или проект",
        ResponseClaimStage.ADOPTED: "решение принято",
        ResponseClaimStage.PUBLISHED: "документ опубликован",
        ResponseClaimStage.FUTURE_EFFECTIVE: "должно вступить в силу позднее",
        ResponseClaimStage.EFFECTIVE: "источник утверждает, что действует",
        ResponseClaimStage.SUPERSEDED: "заменено новой редакцией",
        ResponseClaimStage.REPEALED: "отменено",
        ResponseClaimStage.WITHDRAWN: "отозвано",
        ResponseClaimStage.REJECTED: "отклонено",
        ResponseClaimStage.UNKNOWN: "статус источнику неизвестен",
    }[stage]


def _reliability_label(reliability: ResponseSourceReliability) -> str:
    return {
        ResponseSourceReliability.PRIMARY_OFFICIAL: "первичный нормативный источник",
        ResponseSourceReliability.OFFICIAL: "официальный источник",
        ResponseSourceReliability.TRUSTED_SECONDARY: "надёжный вторичный источник",
        ResponseSourceReliability.UNVERIFIED_SECONDARY: "непроверенный вторичный источник",
        ResponseSourceReliability.COMMUNITY: "сообщество",
        ResponseSourceReliability.USER_SUPPLIED: "материал пользователя",
        ResponseSourceReliability.UNKNOWN: "надёжность неизвестна",
    }[reliability]


def _disposition_label(disposition: RuleDisposition) -> str:
    return {
        RuleDisposition.SELECTED: "выбрано",
        RuleDisposition.CONSIDERED: "рассмотрено без выбора",
        RuleDisposition.NOT_APPLICABLE: "не применимо",
        RuleDisposition.FUTURE: "действует в будущем периоде",
        RuleDisposition.EXPIRED: "срок завершён",
        RuleDisposition.INCOMPLETE_SCOPE: "не хватает области применения",
        RuleDisposition.INCOMPLETE_DATA: "не хватает исходных данных",
        RuleDisposition.UNAVAILABLE: "данные владельца недоступны",
        RuleDisposition.CONFLICT: "участвует в конфликте",
        RuleDisposition.UNRESOLVED: "не удалось разрешить",
    }[disposition]


def _missing_data_label(code: str) -> str:
    return {
        "valid_time": "не задана дата проверки",
        "admission_cycle": "не найден цикл поступления",
        "policy_scope": "не определена область действия",
        "domain_result": "не рассчитан доменный результат",
        "applicant_ege_scores_completeness_unconfirmed": "полнота сведений о результатах ЕГЭ не подтверждена",
        "applicant_internal_exam_scores_completeness_unconfirmed": "полнота сведений о результатах внутренних экзаменов не подтверждена",
        "applicant_olympiad_achievements_completeness_unconfirmed": "полнота сведений об олимпиадных достижениях не подтверждена",
        "applicant_individual_achievements_completeness_unconfirmed": "полнота сведений об индивидуальных достижениях не подтверждена",
        "applicant_confirmation_category_completeness_unconfirmed": "категория подтверждения достижений не указана",
    }.get(code, "не хватает данных для применимости")


def _claim_dates(
    published_at: datetime | None,
    adopted_at: datetime | None,
    effective_from: datetime | None,
    effective_to: datetime | None,
) -> str:
    labels = []
    if published_at is not None:
        labels.append(f"опубликовано {_date_label(published_at)}")
    if adopted_at is not None:
        labels.append(f"принято {_date_label(adopted_at)}")
    if effective_from is not None:
        labels.append(f"действует с {_date_label(effective_from)}")
    if effective_to is not None:
        labels.append(f"действует по {_date_label(effective_to)}")
    return "; ".join(labels)


def _date_label(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y") if value is not None else ""


def _locator_label(
    page: int | None,
    section: str | None,
    table: str | None,
    row: int | None,
) -> str:
    values = []
    if page is not None:
        values.append(f"стр. {page}")
    if section is not None:
        values.append(section)
    if table is not None:
        values.append(f"таблица {table}")
    if row is not None:
        values.append(f"строка {row}")
    return ", ".join(values)


def _bounded_excerpt(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _bounded_text(value: str) -> str:
    limit = 19_700
    if len(value) <= limit:
        return value
    marker = (
        "\n\nТекст сокращён по размеру; полный структурированный результат "
        "и ссылки сохранены в поле knowledge ответа."
    )
    return value[: limit - len(marker)].rstrip() + marker


__all__ = ["KnowledgeResponseRenderer"]
