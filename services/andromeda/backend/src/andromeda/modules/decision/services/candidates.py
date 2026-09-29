"""Candidate orchestration for the decision-centered product model."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
import logging

from andromeda.modules.admission_fit.contracts.public import (
    AdmissionFitReason,
    AdmissionFitReasonKind,
    AdmissionFitBatchEvaluator,
    AdmissionFitStatus,
    ApplicantAdmissionProfile,
    BatchAdmissionFitOutcome,
    BatchAdmissionFitRequest,
)
from andromeda.modules.proftest.contracts.public import MatchScore, RecommendationEvidence, UserProfile
from andromeda.modules.program_analytics.contracts.public import ProgramFingerprint
from andromeda.modules.recommendations.contracts.public import (
    CandidateRankingRequest,
    RecommendationServicePort,
)
from andromeda.shared.contracts.errors import ContractError, ErrorCode
from andromeda.shared.contracts.ids import ProgramId

from ..contracts.public import (
    AdmissionConstraints,
    DecisionCandidatePartition,
    DecisionConstraintApplicability,
    DecisionConstraintOutcome,
    DecisionContext,
    DecisionDataCompleteness,
    DecisionRefinementOption,
    DecisionRefinementQuestion,
    DecisionShortlistItem,
    DecisionSuggestion,
    DecisionSuggestionsResult,
)
from ..domain.values import AdmissionGate, ShortlistRole
from ..repository.ports import ProgramCandidateSnapshot, ProgramCandidateSource
from .explanations import DecisionExplanationBuilder, admission_gate
from .constraints import DecisionConstraintEvaluator


logger = logging.getLogger("andromeda.modules.decision.candidates")

PRIMARY_LIMIT = 3
ALTERNATIVE_LIMIT = 2
DIAGNOSTIC_LIMIT = 20
ADMISSION_BATCH_LIMIT = 50
REFINEMENT_SCORE_GAP = 5
REFINEMENT_AREA_GAP = Decimal("0.12")


@dataclass(frozen=True, slots=True)
class _CandidateEvidence:
    source: ProgramCandidateSnapshot | None
    admission: BatchAdmissionFitOutcome | None
    content_fit: MatchScore | None
    evidence: RecommendationEvidence | None
    constraint_outcomes: tuple[DecisionConstraintOutcome, ...] = ()


class DecisionCandidatePipeline:
    """Build read-only candidate evidence without changing explicit choice state."""

    def __init__(
        self,
        source: ProgramCandidateSource,
        recommendations: RecommendationServicePort,
        admission_fit: AdmissionFitBatchEvaluator,
        explanations: DecisionExplanationBuilder | None = None,
        *,
        primary_limit: int = PRIMARY_LIMIT,
        alternative_limit: int = ALTERNATIVE_LIMIT,
    ) -> None:
        if not 1 <= primary_limit <= PRIMARY_LIMIT:
            raise ValueError("primary_limit must be between 1 and 3")
        if not 0 <= alternative_limit <= ALTERNATIVE_LIMIT:
            raise ValueError("alternative_limit must be between 0 and 2")
        self._source = source
        self._recommendations = recommendations
        self._admission_fit = admission_fit
        self._explanations = explanations or DecisionExplanationBuilder()
        self._constraint_evaluator = DecisionConstraintEvaluator()
        self._primary_limit = primary_limit
        self._alternative_limit = alternative_limit

    def build(self, context: DecisionContext) -> DecisionSuggestionsResult:
        """Return deterministic system suggestions for the current explicit context."""

        sources = tuple(self._source.list_candidates())
        source_by_id = self._index_sources(sources)
        state = context.state
        active_entries = state.choice.active_shortlist
        active_ids = {entry.program_id for entry in active_entries}
        excluded_ids = set(state.choice.excluded_program_ids)
        candidate_sources = tuple(
            item
            for item in sources
            if item.program.id not in active_ids and item.program.id not in excluded_ids
        )
        admission_outcomes = self._evaluate_admission(sources, state.admission_constraints)
        constraint_outcomes = {
            item.program.id: self._constraint_evaluator.evaluate(
                item,
                state.admission_constraints,
                admission_outcomes.get(item.program.id),
            )
            for item in sources
        }
        content_scores = self._rank_content(
            sources,
            active_ids=active_ids,
            excluded_ids=excluded_ids,
            admission_outcomes=admission_outcomes,
            constraint_outcomes=constraint_outcomes,
            profile=context.preferences,
        )
        evidence = {
            item.program.id: _CandidateEvidence(
                source=item,
                admission=admission_outcomes.get(item.program.id),
                content_fit=content_scores.get(item.program.id),
                evidence=self._recommendations.build_evidence(
                    context.preferences,
                    item.fingerprint,
                    profile_revision=context.profile_revision,
                ),
                constraint_outcomes=constraint_outcomes[item.program.id],
            )
            for item in sources
        }

        global_missing, global_source_gaps = self._global_gaps(
            sources=sources,
            constraints=state.admission_constraints,
            profile=context.preferences,
        )
        ineligible_sources = tuple(
            item
            for item in candidate_sources
            if _status_for(evidence[item.program.id]) is AdmissionFitStatus.UNLIKELY
            or _has_constraint_mismatch(evidence[item.program.id].constraint_outcomes)
        )
        insufficient_sources = tuple(
            item
            for item in candidate_sources
            if self._is_insufficient(item, evidence[item.program.id], context.preferences)
        )
        ineligible_ids = {item.program.id for item in ineligible_sources}
        insufficient_ids = {item.program.id for item in insufficient_sources}
        usable_sources = tuple(
            item
            for item in candidate_sources
            if item.program.id not in ineligible_ids and item.program.id not in insufficient_ids
        )
        ordered_usable = self._ordered(usable_sources, content_scores)
        primary_sources = ordered_usable[: self._primary_limit]
        alternative_sources = ordered_usable[self._primary_limit : self._primary_limit + self._alternative_limit]

        primary = tuple(
            self._suggestion(
                evidence[item.program.id],
                partition=DecisionCandidatePartition.PRIMARY,
                profile=context.preferences,
                extra_missing=global_missing,
            )
            for item in primary_sources
        )
        alternatives = tuple(
            self._suggestion(
                evidence[item.program.id],
                partition=DecisionCandidatePartition.ALTERNATIVE,
                profile=context.preferences,
                extra_missing=global_missing,
            )
            for item in alternative_sources
        )
        ineligible = tuple(
            self._suggestion(
                evidence[item.program.id],
                partition=DecisionCandidatePartition.INELIGIBLE,
                profile=context.preferences,
                extra_missing=global_missing,
            )
            for item in self._stable(ineligible_sources)
        )
        insufficient = tuple(
            self._suggestion(
                evidence[item.program.id],
                partition=DecisionCandidatePartition.INSUFFICIENT_DATA,
                profile=context.preferences,
                extra_missing=global_missing,
            )
            for item in self._stable(insufficient_sources)
        )
        active_shortlist = tuple(
            self._shortlist_item(
                entry.program_id,
                role=entry.role,
                evidence=evidence.get(entry.program_id, _CandidateEvidence(None, None, None, None)),
                profile=context.preferences,
                extra_missing=global_missing,
            )
            for entry in active_entries
        )
        source_gaps = _unique((*global_source_gaps, *(gap for item in (*ineligible, *insufficient) for gap in item.source_gaps)), limit=32)
        missing_data = _unique(
            (*global_missing, *(reason for item in (*primary, *alternatives, *ineligible, *insufficient) for reason in item.reasons.missing_data)),
            limit=32,
        )
        if not sources:
            missing_data = _unique((*missing_data, "Канонический каталог программ пока не содержит доступных записей"), limit=32)
        refinement = self._refinement(primary, source_by_id)
        result = DecisionSuggestionsResult(
            decision_id=context.decision_id,
            context_revision=context.state.revision,
            data_completeness=self._completeness(
                sources=sources,
                profile=context.preferences,
                source_gaps=source_gaps,
                missing_data=missing_data,
            ),
            active_shortlist=active_shortlist,
            primary_candidates=primary,
            alternative_candidates=alternatives,
            ineligible_candidates=ineligible[:DIAGNOSTIC_LIMIT],
            insufficient_data_candidates=insufficient[:DIAGNOSTIC_LIMIT],
            suggestions=(*primary, *alternatives),
            refinement_question=refinement,
            source_gaps=source_gaps,
            missing_data=missing_data,
        )
        logger.info(
            "decision_candidates_complete decision_id=%s catalog_count=%d primary_count=%d alternative_count=%d ineligible_count=%d insufficient_count=%d",
            context.decision_id,
            len(sources),
            len(result.primary_candidates),
            len(result.alternative_candidates),
            len(result.ineligible_candidates),
            len(result.insufficient_data_candidates),
        )
        return result

    def _evaluate_admission(
        self,
        sources: tuple[ProgramCandidateSnapshot, ...],
        constraints: AdmissionConstraints | None,
    ) -> dict[ProgramId, BatchAdmissionFitOutcome]:
        if not sources or not _needs_admission_evaluation(constraints):
            return {}
        assert constraints is not None
        applicant = constraints.applicant or ApplicantAdmissionProfile()
        outcomes: dict[ProgramId, BatchAdmissionFitOutcome] = {}
        ids = tuple(item.program.id for item in sources)
        for chunk in _chunks(ids, ADMISSION_BATCH_LIMIT):
            result = self._admission_fit.evaluate_batch(
                BatchAdmissionFitRequest(
                    program_ids=chunk,
                    applicant=applicant,
                    admission_year=constraints.admission_year,
                    study_form=constraints.study_form,
                    funding_type=constraints.funding_preference,
                )
            )
            for program_id in chunk:
                outcome = result.by_program_id.get(program_id)
                if outcome is None:
                    outcome = _missing_admission_outcome(program_id, "Batch Admission Fit не вернул результат для программы")
                outcomes[program_id] = outcome
        return outcomes

    def _rank_content(
        self,
        sources: tuple[ProgramCandidateSnapshot, ...],
        *,
        active_ids: set[ProgramId],
        excluded_ids: set[ProgramId],
        admission_outcomes: dict[ProgramId, BatchAdmissionFitOutcome],
        constraint_outcomes: dict[ProgramId, tuple[DecisionConstraintOutcome, ...]],
        profile: UserProfile | None,
    ) -> dict[ProgramId, MatchScore]:
        if profile is None:
            return {}
        rankable = tuple(
            item
            for item in sources
            if item.program.id not in excluded_ids
            and item.fingerprint is not None
            and not _has_constraint_mismatch(constraint_outcomes.get(item.program.id, ()))
            and (
                item.program.id in active_ids
                or _status_for(admission_outcomes.get(item.program.id)) not in {
                    AdmissionFitStatus.UNLIKELY,
                    AdmissionFitStatus.INSUFFICIENT_DATA,
                }
            )
        )
        if not rankable:
            return {}
        ranking = self._recommendations.rank_candidates(
            CandidateRankingRequest(
                profile=profile,
                fingerprints=tuple(item.fingerprint for item in rankable if item.fingerprint is not None),
                limit=20,
            )
        )
        return {item.fingerprint.program_id: item.score for item in ranking.ranked}

    def _suggestion(
        self,
        evidence: _CandidateEvidence,
        *,
        partition: DecisionCandidatePartition,
        profile: UserProfile | None,
        extra_missing: tuple[str, ...],
    ) -> DecisionSuggestion:
        if evidence.source is None:
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Candidate source is required for a system suggestion")
        reasons, source_gaps = self._explanations.build(
            program=evidence.source.program,
            fingerprint=evidence.source.fingerprint,
            admission=evidence.admission,
            content_fit=evidence.content_fit,
            profile_present=profile is not None,
            partition=partition,
            constraint_outcomes=evidence.constraint_outcomes,
            extra_missing=extra_missing,
        )
        status = _status_for(evidence.admission)
        fingerprint = evidence.source.fingerprint
        provenance = fingerprint.provenance if fingerprint is not None else ()
        source_gap_details = fingerprint.source_gaps if fingerprint is not None else ()
        return DecisionSuggestion(
            program_id=evidence.source.program.id,
            program_code=evidence.source.program.code,
            program_name=evidence.source.program.name,
            partition=partition,
            admission_status=status,
            admission_risk=admission_gate(status),
            admission_fit=evidence.admission.result if evidence.admission is not None else None,
            content_fit=evidence.content_fit,
            evidence=evidence.evidence,
            constraint_outcomes=evidence.constraint_outcomes,
            reasons=reasons,
            source_gaps=source_gaps,
            source_hashes=tuple(dict.fromkeys(item.content_sha256 for item in provenance)),
            provenance=provenance,
            source_gap_details=source_gap_details,
        )

    def _shortlist_item(
        self,
        program_id: ProgramId,
        *,
        role: ShortlistRole,
        evidence: _CandidateEvidence,
        profile: UserProfile | None,
        extra_missing: tuple[str, ...],
    ) -> DecisionShortlistItem:
        program = evidence.source.program if evidence.source is not None else None
        fingerprint = evidence.source.fingerprint if evidence.source is not None else None
        extra = (*extra_missing, "program_source_unavailable" if program is None else "")
        reasons, source_gaps = self._explanations.build(
            program=program,
            fingerprint=fingerprint,
            admission=evidence.admission,
            content_fit=evidence.content_fit,
            profile_present=profile is not None,
            partition=DecisionCandidatePartition.PRIMARY if role is ShortlistRole.PRIMARY else DecisionCandidatePartition.ALTERNATIVE,
            constraint_outcomes=evidence.constraint_outcomes,
            extra_missing=extra,
        )
        status = _status_for(evidence.admission)
        provenance = fingerprint.provenance if fingerprint is not None else ()
        source_gap_details = fingerprint.source_gaps if fingerprint is not None else ()
        return DecisionShortlistItem(
            program_id=program_id,
            program_code=program.code if program is not None else _code_from_id(program_id),
            program_name=program.name if program is not None else None,
            role=role,
            admission_status=status,
            admission_risk=admission_gate(status),
            admission_fit=evidence.admission.result if evidence.admission is not None else None,
            content_fit=evidence.content_fit,
            evidence=evidence.evidence,
            constraint_outcomes=evidence.constraint_outcomes,
            reasons=reasons,
            source_gaps=source_gaps,
            source_hashes=tuple(dict.fromkeys(item.content_sha256 for item in provenance)),
            provenance=provenance,
            source_gap_details=source_gap_details,
        )

    def _refinement(
        self,
        primary: tuple[DecisionSuggestion, ...],
        source_by_id: dict[ProgramId, ProgramCandidateSnapshot],
    ) -> DecisionRefinementQuestion | None:
        if len(primary) < 2:
            return None
        first, second = primary[:2]
        if first.content_fit is None or second.content_fit is None:
            return None
        if abs(first.content_fit.content_fit - second.content_fit.content_fit) > REFINEMENT_SCORE_GAP:
            return None
        first_source = source_by_id.get(first.program_id)
        second_source = source_by_id.get(second.program_id)
        if first_source is None or second_source is None or first_source.fingerprint is None or second_source.fingerprint is None:
            return None
        dimensions = _discriminating_dimensions(first_source.fingerprint, second_source.fingerprint)
        if not dimensions:
            return None
        dimension = dimensions[0]
        options = (
            DecisionRefinementOption(
                id=f"program-{first.program_code}",
                label=first.program_name,
                affected_dimension=dimension,
                effect=f"Сместить уточнение в сторону программы «{first.program_name}»",
            ),
            DecisionRefinementOption(
                id=f"program-{second.program_code}",
                label=second.program_name,
                affected_dimension=dimension,
                effect=f"Сместить уточнение в сторону программы «{second.program_name}»",
            ),
        )
        return DecisionRefinementQuestion(
            id=f"content-tradeoff-{first.program_code}-vs-{second.program_code}",
            prompt="Программы близки по Content Fit. Какой учебный акцент вам ближе?",
            candidate_program_ids=(first.program_id, second.program_id),
            options=options,
            discriminating_dimensions=dimensions,
        )

    @staticmethod
    def _index_sources(sources: tuple[ProgramCandidateSnapshot, ...]) -> dict[ProgramId, ProgramCandidateSnapshot]:
        result: dict[ProgramId, ProgramCandidateSnapshot] = {}
        for item in sources:
            program_id = item.program.id
            if program_id in result:
                raise ContractError(ErrorCode.CONTRACT_ERROR, "Candidate source returned duplicate canonical program IDs")
            result[program_id] = item
        return result

    @staticmethod
    def _ordered(
        sources: tuple[ProgramCandidateSnapshot, ...],
        scores: dict[ProgramId, MatchScore],
    ) -> tuple[ProgramCandidateSnapshot, ...]:
        ranking_order = {program_id: index for index, program_id in enumerate(scores)}
        return tuple(
            sorted(
                sources,
                key=lambda item: (
                    0 if item.program.id in ranking_order else 1,
                    ranking_order.get(item.program.id, 0),
                    item.program.code,
                    item.program.id,
                ),
            )
        )

    @staticmethod
    def _stable(sources: tuple[ProgramCandidateSnapshot, ...]) -> tuple[ProgramCandidateSnapshot, ...]:
        return tuple(sorted(sources, key=lambda item: (item.program.code, item.program.id)))

    @staticmethod
    def _global_gaps(
        *,
        sources: tuple[ProgramCandidateSnapshot, ...],
        constraints: AdmissionConstraints | None,
        profile: UserProfile | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        missing: list[str] = []
        source_gaps: list[str] = []
        if profile is None:
            missing.append("Профиль предпочтений не заполнен")
        if constraints is None:
            missing.append("Ограничения поступления не указаны; Admission Fit не оценивался")
        if not sources:
            source_gaps.append("catalog_empty")
        return _unique(missing, limit=32), _unique(source_gaps, limit=32)

    @staticmethod
    def _is_insufficient(
        source: ProgramCandidateSnapshot,
        evidence: _CandidateEvidence,
        profile: UserProfile | None,
    ) -> bool:
        if _status_for(evidence) is AdmissionFitStatus.INSUFFICIENT_DATA:
            return True
        if any(item.applicability is DecisionConstraintApplicability.INSUFFICIENT_DATA for item in evidence.constraint_outcomes):
            return True
        return profile is not None and source.fingerprint is None

    @staticmethod
    def _completeness(
        *,
        sources: tuple[ProgramCandidateSnapshot, ...],
        profile: UserProfile | None,
        source_gaps: tuple[str, ...],
        missing_data: tuple[str, ...],
    ) -> DecisionDataCompleteness:
        if not sources:
            return DecisionDataCompleteness.UNAVAILABLE
        if profile is None or source_gaps or missing_data:
            return DecisionDataCompleteness.PARTIAL
        return DecisionDataCompleteness.COMPLETE


def _needs_admission_evaluation(constraints: AdmissionConstraints | None) -> bool:
    if constraints is None:
        return False
    return any(
        value is not None
        for value in (
            constraints.applicant,
            constraints.admission_year,
            constraints.funding_preference,
            constraints.study_form,
        )
    )


def _status_for(evidence: _CandidateEvidence | BatchAdmissionFitOutcome | None) -> AdmissionFitStatus | None:
    if isinstance(evidence, _CandidateEvidence):
        return evidence.admission.status if evidence.admission is not None else None
    return evidence.status if evidence is not None else None


def _has_constraint_mismatch(outcomes: tuple[DecisionConstraintOutcome, ...]) -> bool:
    return any(
        outcome.applicability is not DecisionConstraintApplicability.NOT_APPLICABLE
        and outcome.satisfied is False
        for outcome in outcomes
    )


def _missing_admission_outcome(program_id: ProgramId, message: str) -> BatchAdmissionFitOutcome:
    reason = AdmissionFitReason(kind=AdmissionFitReasonKind.DATA_GAP, message=message)
    return BatchAdmissionFitOutcome(
        program_id=program_id,
        status=AdmissionFitStatus.INSUFFICIENT_DATA,
        data_gaps=(reason,),
    )


def _chunks(values: tuple[ProgramId, ...], size: int) -> Iterable[tuple[ProgramId, ...]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _discriminating_dimensions(first: ProgramFingerprint, second: ProgramFingerprint) -> tuple[str, ...]:
    """Return the largest explainable differences between two candidates.

    The refinement question is intentionally derived from vectors already
    used by Content Fit.  Subject, activity and distinctive-content features
    share one deterministic ranking; no generated question or runtime model
    is involved.  A dimension is returned only when the gap is large enough
    to plausibly change the ordering after a future answer is applied.
    """

    gaps: list[tuple[Decimal, str]] = []
    for area in set(first.area_share) | set(second.area_share):
        gap = abs(first.area_share.get(area, Decimal("0")) - second.area_share.get(area, Decimal("0")))
        if gap >= REFINEMENT_AREA_GAP:
            gaps.append((gap, f"subject:{area.value}"))
    for activity in set(first.activity_signals) | set(second.activity_signals):
        gap = abs(first.activity_signals.get(activity, Decimal("0")) - second.activity_signals.get(activity, Decimal("0")))
        if gap >= REFINEMENT_AREA_GAP:
            gaps.append((gap, f"activity:{activity.value}"))

    first_content = _distinctive_content_vector(first)
    second_content = _distinctive_content_vector(second)
    for feature in set(first_content) | set(second_content):
        gap = abs(first_content.get(feature, Decimal("0")) - second_content.get(feature, Decimal("0")))
        if gap >= REFINEMENT_AREA_GAP:
            gaps.append((gap, f"content:{feature}"))

    gaps.sort(key=lambda item: (-item[0], item[1]))
    return tuple(dimension for _gap, dimension in gaps[:4])


def _distinctive_content_vector(fingerprint: ProgramFingerprint) -> dict[str, Decimal]:
    """Build a bounded content signal from already persisted fingerprint data."""

    return {
        subject.normalized_name: subject.share * subject.distinctiveness
        for subject in fingerprint.distinctive_subjects
        if subject.normalized_name
    }


def _code_from_id(program_id: ProgramId) -> str:
    return program_id.removeprefix("program:")


def _unique(values: Iterable[str], *, limit: int) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) >= limit:
            break
    return tuple(result)


__all__ = ["DecisionCandidatePipeline"]
