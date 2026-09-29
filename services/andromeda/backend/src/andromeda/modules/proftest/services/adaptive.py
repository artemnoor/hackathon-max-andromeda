"""Select and materialize adaptive questions from candidate spread."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from andromeda.shared.contracts.provenance import GapSeverity
import logging
from typing import Literal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode, area_definition

from ..contracts.public import ActivityCode, AdaptiveDimension, AdaptiveSelection, AdaptiveStatus, AdaptiveStopReason, Question, QuestionBlock, QuestionComponentType, QuestionOption, QuestionStage, UserProfile
from ..domain.entities import ProgramFingerprint
from ..domain.values import quantize_ratio


logger = logging.getLogger("andromeda.proftest.adaptive")

MAX_ADAPTIVE_QUESTIONS_V2 = 10
MAX_ADAPTIVE_QUESTIONS_V3 = 4
MIN_ADAPTIVE_ANSWERS_BEFORE_STOP_V3 = 2
TOP_THREE_SIZE = 3
TOP_THREE_SCORE_DELTA_V3 = 3


@dataclass(frozen=True, slots=True)
class AdaptiveCandidate:
    fingerprint: ProgramFingerprint
    score: Decimal


class AdaptiveQuestionSelector:
    def __init__(
        self,
        *,
        top_limit: int = 10,
        min_spread: Decimal = Decimal("0.08"),
        max_adaptive_questions: int = MAX_ADAPTIVE_QUESTIONS_V2,
        min_answers_before_stop: int = MIN_ADAPTIVE_ANSWERS_BEFORE_STOP_V3,
        stability_score_delta: int = TOP_THREE_SCORE_DELTA_V3,
    ) -> None:
        self._top_limit = top_limit
        self._min_spread = min_spread
        self._max_adaptive_questions = max_adaptive_questions
        self._min_answers_before_stop = min_answers_before_stop
        self._stability_score_delta = stability_score_delta

    def select(
        self,
        candidates: tuple[AdaptiveCandidate, ...],
        profile: UserProfile | None = None,
        *,
        asked_question_ids: tuple[str, ...] = (),
        asked_dimensions: tuple[str, ...] = (),
        adaptive_count: int = 0,
        ranking_snapshots: tuple[tuple[str, ...], ...] = (),
        ranking_score_snapshots: tuple[tuple[int, ...], ...] = (),
    ) -> AdaptiveSelection:
        ranked = tuple(sorted(candidates, key=lambda candidate: (-candidate.score, candidate.fingerprint.program_code)))
        top = ranked[: self._top_limit]
        if len(top) < 2:
            logger.warning("adaptive_skip_insufficient_candidates candidate_count=%d", len(top))
            return AdaptiveSelection(status=AdaptiveStatus.SKIPPED, reason="Недостаточно программ для осмысленного уточнения.", candidate_count=len(ranked), top_candidate_count=len(top), asked_question_ids=asked_question_ids, adaptive_count=adaptive_count, stop_reason=AdaptiveStopReason.INSUFFICIENT_CANDIDATES)
        if all(
            GapSeverity.BLOCKING in {gap.severity for gap in candidate.fingerprint.source_gaps}
            for candidate in top
        ):
            logger.warning("adaptive_skip_blocking_source_gap candidate_count=%d", len(top))
            return AdaptiveSelection(
                status=AdaptiveStatus.SKIPPED,
                reason="В каталоге недостаточно подтверждённых данных для дополнительного уточнения.",
                candidate_count=len(ranked),
                top_candidate_count=len(top),
                asked_question_ids=asked_question_ids,
                adaptive_count=adaptive_count,
                stop_reason=AdaptiveStopReason.SOURCE_GAP,
            )
        if adaptive_count >= self._max_adaptive_questions:
            return AdaptiveSelection(status=AdaptiveStatus.SKIPPED, reason="Достигнут лимит уточняющих вопросов.", candidate_count=len(ranked), top_candidate_count=len(top), asked_question_ids=asked_question_ids, adaptive_count=adaptive_count, stop_reason=AdaptiveStopReason.MAX_QUESTIONS)
        stop_reason = _stable_stop_reason(
            top,
            adaptive_count=adaptive_count,
            ranking_snapshots=ranking_snapshots,
            ranking_score_snapshots=ranking_score_snapshots,
            min_answers_before_stop=self._min_answers_before_stop,
            max_score_delta=self._stability_score_delta,
        )
        if stop_reason is not None:
            logger.info("adaptive_stop_selected reason=%s adaptive_count=%d top_k=%d", stop_reason.value, adaptive_count, len(top))
            return AdaptiveSelection(
                status=AdaptiveStatus.SKIPPED,
                reason="Профиль уже достаточно устойчив для рекомендаций.",
                candidate_count=len(ranked),
                top_candidate_count=len(top),
                asked_question_ids=asked_question_ids,
                adaptive_count=adaptive_count,
                stop_reason=stop_reason,
            )
        dimensions = _dimensions(top)
        scored: list[AdaptiveDimension] = []
        for code, kind, label in dimensions:
            if code in asked_dimensions:
                continue
            values = tuple(_dimension_value(candidate.fingerprint, code, kind) for candidate in top)
            spread = max(values) - min(values)
            average = sum(values, Decimal("0")) / Decimal(len(values))
            confidence = profile.confidence_by_dimension.get(code, Decimal("0")) if profile is not None else Decimal("0")
            uncertainty = Decimal("1") - confidence
            significance = min(Decimal("1"), spread * (Decimal("0.5") + average) * uncertainty)
            if spread >= self._min_spread and uncertainty > Decimal("0"):
                scored.append(AdaptiveDimension(code=code, label=label, kind=kind, spread=quantize_ratio(spread), significance=quantize_ratio(significance)))
        scored.sort(key=lambda dimension: (-dimension.significance, -dimension.spread, dimension.code))
        if len(scored) < 2:
            stop_reason = AdaptiveStopReason.SOURCE_GAP if not dimensions else AdaptiveStopReason.NO_MEANINGFUL_QUESTION
            logger.warning("adaptive_skip_no_question reason=%s meaningful_count=%d", stop_reason.value, len(scored))
            return AdaptiveSelection(status=AdaptiveStatus.SKIPPED, reason="В текущем наборе программ нет двух достаточно различающихся направлений.", candidate_count=len(ranked), top_candidate_count=len(top), dimensions=tuple(scored[:2]), asked_question_ids=asked_question_ids, adaptive_count=adaptive_count, stop_reason=stop_reason)
        logger.info("adaptive_question_selected dimension_count=2 candidate_count=%d", len(top))
        return AdaptiveSelection(status=AdaptiveStatus.READY, candidate_count=len(ranked), top_candidate_count=len(top), dimensions=tuple(scored[:2]), asked_question_ids=asked_question_ids, adaptive_count=adaptive_count)


class AdaptiveQuestionFactory:
    def create(self, selection: AdaptiveSelection, *, sequence: int = 0) -> Question | None:
        if selection.status is not AdaptiveStatus.READY or len(selection.dimensions) < 2:
            return None
        first, second = selection.dimensions
        first_subjects, first_activities = _dimension_weights(first)
        second_subjects, second_activities = _dimension_weights(second)
        components = (QuestionComponentType.PAIR_CHOICE, QuestionComponentType.SCENARIO_CHOICE, QuestionComponentType.ANCHORED_SCALE)
        component = components[sequence % len(components)]
        return Question(
            id=f"adaptive_{sequence}_{first.code.replace(':', '_')}_{second.code.replace(':', '_')}",
            block=QuestionBlock.ADAPTIVE,
            stage=QuestionStage.CLARIFICATION,
            component_type=component,
            order=100 + sequence,
            prompt=f"Что тебе ближе: {first.label.lower()} или {second.label.lower()}?",
            adaptive=True,
            declared_dimensions=(first.code, second.code),
            options=(
                QuestionOption(id="prefer_first", label=first.label, subject_weights=first_subjects, activity_weights=first_activities),
                QuestionOption(id="prefer_second", label=second.label, subject_weights=second_subjects, activity_weights=second_activities),
                QuestionOption(id="balanced", label="Сочетать оба направления", subject_weights={**first_subjects, **second_subjects}, activity_weights={**first_activities, **second_activities}),
            ),
        )


def _dimensions(candidates: tuple[AdaptiveCandidate, ...]) -> tuple[tuple[str, Literal["area", "activity"], str], ...]:
    areas = sorted({area for candidate in candidates for area in candidate.fingerprint.area_share}, key=lambda area: area.value)
    activities = sorted({activity for candidate in candidates for activity in candidate.fingerprint.activity_signals}, key=lambda activity: activity.value)
    return tuple([(f"area:{area.value}", "area", area_definition(area).name) for area in areas] + [(f"activity:{activity.value}", "activity", _activity_label(activity)) for activity in activities])


def _dimension_value(fingerprint: ProgramFingerprint, code: str, kind: Literal["area", "activity"]) -> Decimal:
    _, value = code.split(":", maxsplit=1)
    if kind == "area":
        return fingerprint.area_share.get(DisciplineAreaCode(value), Decimal("0"))
    return fingerprint.activity_signals.get(ActivityCode(value), Decimal("0"))


def _dimension_weights(dimension: AdaptiveDimension) -> tuple[dict[DisciplineAreaCode, Decimal], dict[ActivityCode, Decimal]]:
    _, value = dimension.code.split(":", maxsplit=1)
    if dimension.kind == "area":
        return {DisciplineAreaCode(value): Decimal("1")}, {}
    return {}, {ActivityCode(value): Decimal("1")}


def _stable_stop_reason(
    top: tuple[AdaptiveCandidate, ...],
    *,
    adaptive_count: int,
    ranking_snapshots: tuple[tuple[str, ...], ...],
    ranking_score_snapshots: tuple[tuple[int, ...], ...],
    min_answers_before_stop: int,
    max_score_delta: int,
) -> AdaptiveStopReason | None:
    """Return a stop only after comparing two bounded ranking observations."""

    if adaptive_count < min_answers_before_stop or len(ranking_snapshots) < 2 or len(ranking_score_snapshots) < 2:
        return None
    previous_ids = ranking_snapshots[-2][:TOP_THREE_SIZE]
    current_ids = ranking_snapshots[-1][:TOP_THREE_SIZE]
    if previous_ids != current_ids:
        return None
    previous_scores = ranking_score_snapshots[-2]
    current_scores = ranking_score_snapshots[-1]
    compared = min(len(previous_scores), len(current_scores), len(top))
    if compared == 0:
        return None
    delta = max(abs(current_scores[index] - previous_scores[index]) for index in range(compared))
    logger.debug("adaptive_stability_checked adaptive_count=%d top_k=%d delta=%d", adaptive_count, len(top), delta)
    if delta == 0:
        return AdaptiveStopReason.TOP_THREE_STABLE
    if delta <= max_score_delta:
        return AdaptiveStopReason.LOW_RANKING_IMPACT
    return None


def _activity_label(activity: ActivityCode) -> str:
    return {
        ActivityCode.ANALYTICAL: "Анализировать и находить закономерности",
        ActivityCode.SOFTWARE_CREATION: "Создавать цифровые инструменты",
        ActivityCode.SYSTEM_DESIGN: "Проектировать системы",
        ActivityCode.RESEARCH: "Исследовать и проверять гипотезы",
        ActivityCode.PHYSICAL_ENGINEERING: "Собирать и проверять физические решения",
        ActivityCode.COMMUNICATION: "Объяснять и работать с людьми",
        ActivityCode.CREATIVE: "Придумывать и визуализировать",
        ActivityCode.BUSINESS: "Организовывать и принимать решения",
        ActivityCode.DATA: "Работать с данными",
    }[activity]


__all__ = [
    "AdaptiveCandidate",
    "AdaptiveQuestionFactory",
    "AdaptiveQuestionSelector",
    "MAX_ADAPTIVE_QUESTIONS_V2",
    "MAX_ADAPTIVE_QUESTIONS_V3",
    "MIN_ADAPTIVE_ANSWERS_BEFORE_STOP_V3",
    "TOP_THREE_SCORE_DELTA_V3",
]
