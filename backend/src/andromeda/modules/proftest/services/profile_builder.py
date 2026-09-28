"""Convert validated answers into the stable UserProfile contract."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import logging

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode

from ..contracts.public import ActivityCode, AnswerSet, AnswerStatus, AntiInterest, Confidence, Question, UserProfile
from ..domain.profiling import normalize_weights
from ..domain.values import ZERO, clamp, quantize_ratio


logger = logging.getLogger("andromeda.proftest.profiling")


class UserProfileBuilder:
    def build(self, answer_set: AnswerSet, questions: tuple[Question, ...], adaptive_questions: tuple[Question, ...] = ()) -> UserProfile:
        question_map = {question.id: question for question in (*questions, *adaptive_questions)}
        subject_weights: defaultdict[DisciplineAreaCode, Decimal] = defaultdict(lambda: ZERO)
        activity_weights: defaultdict[ActivityCode, Decimal] = defaultdict(lambda: ZERO)
        negative_weights: defaultdict[DisciplineAreaCode, Decimal] = defaultdict(lambda: ZERO)
        interests: set[DisciplineAreaCode] = set()
        activities: set[ActivityCode] = set()
        anti_interests: dict[DisciplineAreaCode, Decimal] = {}
        base_answer_count = 0
        confidence_by_dimension: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
        dimension_observations: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
        decision_context: set[str] = set()
        hard_filters: set[str] = set()
        format_preferences: set[str] = set()
        load_values: list[Decimal] = []

        def apply_option(question: Question, option_id: str, intensity: Decimal) -> None:
            option_map = {option.id: option for option in question.options}
            option = option_map.get(option_id)
            if option is None:
                logger.error("profile_unknown_option question_id=%s", _safe_id(question.id))
                raise ValueError("Unknown option")
            for area, weight in option.subject_weights.items():
                subject_weights[area] += weight
                interests.add(area)
            for activity, weight in option.activity_weights.items():
                activity_weights[activity] += weight
                activities.add(activity)
            for area, weight in option.anti_interest_weights.items():
                combined = clamp(anti_interests.get(area, ZERO) + (weight * intensity))
                anti_interests[area] = combined
                negative_weights[area] = combined
            decision_context.update(option.context_tags)
            hard_filters.update(option.filter_tags)
            format_preferences.update(option.format_tags)

            if question.id == "anti_load":
                load_values.append({"low_load": Decimal("0.25"), "balanced_load": Decimal("0.60"), "high_load": Decimal("0.90")}.get(option_id, Decimal("0.60")))

        for answer in answer_set.answers:
            question = question_map.get(answer.question_id)
            if question is None:
                logger.error("profile_unknown_question question_id=%s", _safe_id(answer.question_id))
                raise ValueError("Unknown question")
            if len(answer.option_ids) > question.max_selected:
                raise ValueError("Too many selected options")
            if answer.status is AnswerStatus.ANSWERED:
                for option_id in answer.option_ids:
                    intensity = answer.intensity if answer.intensity is not None else Decimal("1")
                    apply_option(question, option_id, intensity)
                base_answer_count += 1
                confidence_increment = Decimal("1")
            elif answer.status is AnswerStatus.UNCERTAIN:
                confidence_increment = Decimal("0.25")
            else:
                confidence_increment = ZERO
            for dimension in question.declared_dimensions:
                dimension_observations[dimension] += Decimal("1")
                confidence_by_dimension[dimension] += confidence_increment

        adaptive_count = 0
        for adaptive_answer in answer_set.adaptive_answers:
            question = question_map.get(adaptive_answer.question_id)
            if question is None or not question.adaptive:
                logger.error("profile_unknown_adaptive_question question_id=%s", _safe_id(adaptive_answer.question_id))
                raise ValueError("Unknown adaptive question")
            apply_option(question, adaptive_answer.option_id, Decimal("1"))
            adaptive_count += 1
            for dimension in question.declared_dimensions or (adaptive_answer.dimension,):
                dimension_observations[dimension] += Decimal("1")
                confidence_by_dimension[dimension] += Decimal("1")
        normalized_confidence = {
            dimension: quantize_ratio(clamp(value / dimension_observations[dimension]))
            for dimension, value in sorted(confidence_by_dimension.items())
            if dimension_observations[dimension] > ZERO
        }
        consistency_flags: set[str] = set()
        if {"individual_focus", "teamwork"} <= format_preferences:
            consistency_flags.add("teamwork_preference_mixed")
        if {"theory_first", "hands_on"} <= format_preferences:
            consistency_flags.add("learning_format_mixed")
        load_tolerance = sum(load_values, ZERO) / Decimal(len(load_values)) if load_values else None
        profile = UserProfile(
            interests=tuple(sorted(interests, key=lambda area: area.value)),
            activity_preferences=tuple(sorted(activities, key=lambda activity: activity.value)),
            anti_interests=tuple(AntiInterest(area=area, intensity=intensity) for area, intensity in sorted(anti_interests.items(), key=lambda entry: entry[0].value)),
            preferred_subject_weights=normalize_weights(subject_weights),
            preferred_activity_weights=normalize_weights(activity_weights),
            negative_weights=dict(sorted(negative_weights.items(), key=lambda entry: entry[0].value)),
            confidence=Confidence(
                value=quantize_ratio(clamp(Decimal(base_answer_count) / Decimal(max(1, len(questions))) + Decimal("0.1") * min(adaptive_count, 2))),
                answered_base=base_answer_count,
                answered_adaptive=adaptive_count,
            ),
            adaptive_answers=answer_set.adaptive_answers,
            decision_context=tuple(sorted(decision_context)),
            hard_filters=tuple(sorted(hard_filters)),
            format_preferences=tuple(sorted(format_preferences)),
            load_tolerance=load_tolerance,
            confidence_by_dimension=normalized_confidence,
            consistency_flags=tuple(sorted(consistency_flags)),
        )
        logger.info("profile_built answered_base=%d answered_adaptive=%d subject_axes=%d activity_axes=%d anti_axes=%d confidence_axes=%d", base_answer_count, adaptive_count, len(profile.preferred_subject_weights), len(profile.preferred_activity_weights), len(profile.negative_weights), len(profile.confidence_by_dimension))
        return profile


def _safe_id(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")[:128]


__all__ = ["UserProfileBuilder"]
