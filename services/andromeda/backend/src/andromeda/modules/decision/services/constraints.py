"""Source-backed evaluation of explicit decision constraints."""

from __future__ import annotations

from collections.abc import Callable

from andromeda.modules.admission_fit.contracts.public import AdmissionFitStatus, BatchAdmissionFitOutcome
from andromeda.modules.admissions.contracts.public import AdmissionOffering, FundingType, StudyForm, TuitionCost

from ..contracts.public import (
    AdmissionConstraints,
    DecisionConstraintApplicability,
    DecisionConstraintDimension,
    DecisionConstraintOutcome,
)
from ..repository.ports import ProgramCandidateSnapshot


RUBLE_CURRENCIES = frozenset({"RUB", "RUR", "₽"})


class DecisionConstraintEvaluator:
    """Evaluate only facts present in one candidate snapshot.

    An absent snapshot is never treated as a passing value.  ``APPLIED``
    means the comparison was possible, while ``INSUFFICIENT_DATA`` preserves
    the candidate and tells the caller why it must not be presented as a fit.
    """

    def evaluate(
        self,
        snapshot: ProgramCandidateSnapshot,
        constraints: AdmissionConstraints | None,
        admission: BatchAdmissionFitOutcome | None,
    ) -> tuple[DecisionConstraintOutcome, ...]:
        if constraints is None:
            return ()
        result: list[DecisionConstraintOutcome] = []
        if constraints.applicant is not None:
            result.append(self._applicant(admission))
        if constraints.admission_year is not None:
            result.append(self._offering_dimension(snapshot, DecisionConstraintDimension.ADMISSION_YEAR, "год поступления", constraints.admission_year, lambda item: item.admission_year))
        if constraints.funding_preference is not None:
            result.append(self._offering_dimension(snapshot, DecisionConstraintDimension.FUNDING, "тип финансирования", constraints.funding_preference.value, lambda item: item.funding_type))
        if constraints.study_form is not None:
            result.append(self._offering_dimension(snapshot, DecisionConstraintDimension.STUDY_FORM, "форма обучения", constraints.study_form.value, lambda item: item.study_form))
        if constraints.max_tuition is not None:
            result.append(self._tuition(snapshot, constraints))
        if constraints.location is not None:
            result.append(self._location(snapshot, constraints.location))
        return tuple(result)

    @staticmethod
    def _applicant(admission: BatchAdmissionFitOutcome | None) -> DecisionConstraintOutcome:
        dimension = DecisionConstraintDimension.APPLICANT_SCORES
        if admission is None or admission.result is None:
            return _insufficient(dimension, "Баллы абитуриента не сопоставлены с опубликованными требованиями", "decision_constraint_source_missing:applicant_scores")
        if admission.status is AdmissionFitStatus.INSUFFICIENT_DATA:
            return _insufficient(dimension, "Баллы абитуриента оценены не полностью: не хватает данных приёмной кампании", "decision_constraint_source_incomplete:applicant_scores")
        satisfied = admission.status is not AdmissionFitStatus.UNLIKELY
        message = "Баллы абитуриента сопоставлены с опубликованными требованиями" if satisfied else "Баллы абитуриента не соответствуют одному или нескольким опубликованным ограничениям"
        return _applied(dimension, satisfied, message)

    @staticmethod
    def _offering_dimension(
        snapshot: ProgramCandidateSnapshot,
        dimension: DecisionConstraintDimension,
        label: str,
        expected: object,
        getter: Callable[[AdmissionOffering], object | None],
    ) -> DecisionConstraintOutcome:
        if snapshot.admissions is None or not snapshot.admissions.offerings:
            return _insufficient(dimension, f"{label.capitalize()} не проверен: для программы нет опубликованных offerings", f"decision_constraint_source_missing:{dimension.value}")
        known_mismatch = False
        unknown_value = False
        for offering in snapshot.admissions.offerings:
            actual = getter(offering)
            if actual is None:
                unknown_value = True
                continue
            actual_value = actual.value if hasattr(actual, "value") else actual
            if actual_value == expected:
                return _applied(dimension, True, f"{label.capitalize()} совпадает с offering программы")
            known_mismatch = True
        if unknown_value:
            return _insufficient(dimension, f"{label.capitalize()} не определён для всех подходящих offerings", f"decision_constraint_source_incomplete:{dimension.value}")
        if known_mismatch:
            return _applied(dimension, False, f"У программы нет offering с указанным значением: {expected}")
        return _insufficient(dimension, f"{label.capitalize()} не удалось сопоставить с offering", f"decision_constraint_source_incomplete:{dimension.value}")

    @staticmethod
    def _tuition(snapshot: ProgramCandidateSnapshot, constraints: AdmissionConstraints) -> DecisionConstraintOutcome:
        dimension = DecisionConstraintDimension.MAX_TUITION
        max_tuition = constraints.max_tuition
        assert max_tuition is not None
        if constraints.funding_preference is FundingType.BUDGET:
            return _not_applicable(dimension, "Максимальная стоимость не применяется к выбранному бюджетному финансированию")
        if snapshot.admissions is None or not snapshot.admissions.offerings:
            return _insufficient(dimension, "Стоимость не проверена: для программы нет опубликованных offerings", "decision_constraint_source_missing:max_tuition")

        matching, uncertain = _matching_offerings(snapshot.admissions.offerings, constraints)
        if not matching:
            if uncertain:
                return _insufficient(dimension, "Стоимость не проверена: год, форма или финансирование offering неизвестны", "decision_constraint_source_incomplete:max_tuition")
            return _not_applicable(dimension, "Для выбранного года, формы и финансирования нет сопоставимого платного offering")

        comparable: list[TuitionCost] = []
        unsupported_currency = False
        missing_cost = False
        for offering in matching:
            if offering.funding_type is FundingType.BUDGET:
                continue
            if not offering.tuition:
                missing_cost = True
                continue
            for cost in offering.tuition:
                if cost.study_form is not None and constraints.study_form is not None and cost.study_form is not constraints.study_form:
                    continue
                if _currency_code(cost.currency) in RUBLE_CURRENCIES:
                    comparable.append(cost)
                else:
                    unsupported_currency = True
        if comparable:
            satisfied = any(cost.amount <= max_tuition for cost in comparable)
            boundary = min(cost.amount for cost in comparable)
            message = (
                f"Стоимость сопоставлена: минимально опубликованная цена {boundary} ₽ не превышает лимит"
                if satisfied
                else f"Стоимость сопоставлена: минимально опубликованная цена {boundary} ₽ выше лимита"
            )
            return _applied(dimension, satisfied, message)
        if missing_cost or unsupported_currency:
            return _insufficient(dimension, "Стоимость не сопоставлена: отсутствует сумма в рублях или валюта не поддерживается", "decision_constraint_source_incomplete:max_tuition")
        return _not_applicable(dimension, "В выбранных offerings нет сопоставимой платной стоимости")

    @staticmethod
    def _location(snapshot: ProgramCandidateSnapshot, requested: str) -> DecisionConstraintOutcome:
        dimension = DecisionConstraintDimension.LOCATION
        if snapshot.university is None:
            return _insufficient(dimension, "Место обучения не проверено: у программы нет авторитетной географии университета", "decision_constraint_source_missing:location")
        expected = _normalize_location(requested)
        actual = _normalize_location(snapshot.university.city)
        if expected == actual:
            return _applied(dimension, True, f"Место обучения совпадает с городом университета: {snapshot.university.city}")
        return _applied(dimension, False, f"Город университета ({snapshot.university.city}) не совпадает с указанным местом")


def _matching_offerings(
    offerings: tuple[AdmissionOffering, ...],
    constraints: AdmissionConstraints,
) -> tuple[tuple[AdmissionOffering, ...], bool]:
    matched: list[AdmissionOffering] = []
    uncertain = False
    for offering in offerings:
        state = _offering_match_state(offering, constraints)
        if state is True:
            matched.append(offering)
        elif state is None:
            uncertain = True
    return tuple(matched), uncertain


def _offering_match_state(offering: AdmissionOffering, constraints: AdmissionConstraints) -> bool | None:
    checks: tuple[tuple[object | None, object | None], ...] = (
        (offering.admission_year, constraints.admission_year),
        (offering.funding_type, constraints.funding_preference),
        (offering.study_form, constraints.study_form),
    )
    uncertain = False
    for actual, expected in checks:
        if expected is None:
            continue
        if actual is None:
            uncertain = True
            continue
        if actual is not expected and actual != expected:
            return False
    return None if uncertain else True


def _currency_code(value: str) -> str:
    return value.strip().upper().replace("РУБ.", "RUB").replace("РУБ", "RUB")


def _normalize_location(value: str) -> str:
    return " ".join(value.casefold().split()).removeprefix("г. ")


def _applied(dimension: DecisionConstraintDimension, satisfied: bool, message: str) -> DecisionConstraintOutcome:
    return DecisionConstraintOutcome(dimension=dimension, applicability=DecisionConstraintApplicability.APPLIED, satisfied=satisfied, message=message)


def _not_applicable(dimension: DecisionConstraintDimension, message: str) -> DecisionConstraintOutcome:
    return DecisionConstraintOutcome(dimension=dimension, applicability=DecisionConstraintApplicability.NOT_APPLICABLE, message=message)


def _insufficient(dimension: DecisionConstraintDimension, message: str, source_gap: str) -> DecisionConstraintOutcome:
    return DecisionConstraintOutcome(
        dimension=dimension,
        applicability=DecisionConstraintApplicability.INSUFFICIENT_DATA,
        message=message,
        source_gaps=(source_gap,),
    )


__all__ = ["DecisionConstraintEvaluator"]
