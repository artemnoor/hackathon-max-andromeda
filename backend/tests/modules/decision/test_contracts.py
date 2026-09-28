from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.admission_fit.contracts.public import ApplicantAdmissionProfile, ApplicantSubjectScore
from andromeda.modules.admissions.contracts.public import FundingType
from andromeda.modules.decision.contracts.public import (
    AdmissionConstraints,
    DecisionContext,
    DecisionContextMetadata,
    DecisionRefinementQuestion,
    DecisionSuggestion,
    DecisionSuggestionReasons,
    DecisionState,
    ShortlistEntry,
    ShortlistEntryState,
    ShortlistRole,
)
from andromeda.modules.decision.domain.entities import DecisionChoice
from andromeda.modules.decision.domain.values import AdmissionGate, DecisionId
from andromeda.shared.contracts.ids import ProgramId


NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
PROGRAM_A: ProgramId = "program:09.03.01-01"
PROGRAM_B: ProgramId = "program:09.03.01-02"


def _entry(program_id: ProgramId, *, state: ShortlistEntryState = ShortlistEntryState.ACTIVE) -> ShortlistEntry:
    return ShortlistEntry(
        program_id=program_id,
        role=ShortlistRole.PRIMARY,
        state=state,
        created_at=NOW,
        updated_at=NOW,
        removed_at=NOW if state is ShortlistEntryState.REMOVED else None,
    )


def _state(*, choice: DecisionChoice | None = None) -> DecisionState:
    return DecisionState(
        choice=choice or DecisionChoice(),
        created_at=NOW,
        updated_at=NOW,
    )


def test_admission_constraints_keep_exam_facts_separate_from_content_fit() -> None:
    constraints = AdmissionConstraints(
        applicant=ApplicantAdmissionProfile(
            scores=(ApplicantSubjectScore(subject="Математика", score=Decimal("82")),),
        ),
        admission_year=2026,
        funding_preference=FundingType.BUDGET,
        max_tuition=Decimal("125000.50"),
    )

    assert constraints.max_tuition == Decimal("125000.50")
    assert constraints.applicant is not None
    assert "preferred_subject_weights" not in constraints.model_dump()


def test_choice_rejects_duplicates_and_active_excluded_overlap() -> None:
    with pytest.raises(ValidationError):
        DecisionChoice(considered_program_ids=(PROGRAM_A, PROGRAM_A))

    with pytest.raises(ValidationError):
        DecisionChoice(
            shortlist_entries=(_entry(PROGRAM_A),),
            excluded_program_ids=(PROGRAM_A,),
        )


def test_removed_entry_is_explicit_and_restorable() -> None:
    removed = _entry(PROGRAM_A, state=ShortlistEntryState.REMOVED)
    assert removed.removed_at == NOW

    with pytest.raises(ValidationError):
        ShortlistEntry(
            program_id=PROGRAM_A,
            role=ShortlistRole.PRIMARY,
            state=ShortlistEntryState.REMOVED,
            created_at=NOW,
            updated_at=NOW,
        )


def test_context_keeps_metadata_revision_and_profile_revision_separate() -> None:
    state = _state()
    context = DecisionContext(
        decision_id="decision:" + "a" * 32,
        state=state,
        profile_revision=3,
        missing_data=("max_tuition",),
        metadata=DecisionContextMetadata(
            decision_id="decision:" + "a" * 32,
            revision=state.revision,
            status=state.status,
            created_at=NOW,
            updated_at=NOW,
            profile_revision=3,
        ),
    )

    assert context.metadata.status.value == "empty"
    assert context.profile_revision == 3

    with pytest.raises(ValidationError):
        DecisionContext(
            decision_id="decision:" + "a" * 32,
            state=state,
            metadata=DecisionContextMetadata(
                decision_id="decision:" + "a" * 32,
                revision=2,
                status=state.status,
                created_at=NOW,
                updated_at=NOW,
            ),
        )


def test_suggestion_has_separate_evidence_buckets_and_no_global_score() -> None:
    suggestion = DecisionSuggestion(
        program_id=PROGRAM_A,
        program_code="09.03.01-01",
        program_name="Информатика и вычислительная техника",
        admission_risk=AdmissionGate.BORDERLINE,
        reasons=DecisionSuggestionReasons(
            why_included=("Есть source-backed curriculum evidence",),
            why_may_not_fit=("Нагрузка по математике выше ожидаемой",),
            admission_risk=("Исторический порог близок к введённым данным",),
            content_differences=("Больше дисциплин по программированию",),
            missing_data=("study_form",),
        ),
    )
    payload = suggestion.model_dump()

    assert suggestion.admission_risk is AdmissionGate.BORDERLINE
    assert "score" not in payload
    assert "why_included" in payload["reasons"]
    assert "why_may_not_fit" in payload["reasons"]


def test_refinement_question_is_bounded_to_current_candidates() -> None:
    question = DecisionRefinementQuestion(
        id="question:engineering-vs-data",
        prompt="Что вам ближе?",
        candidate_program_ids=(PROGRAM_A, PROGRAM_B),
        options=(
            {"id": "engineering", "label": "Инженерные системы", "affected_dimension": "system_design"},
            {"id": "data", "label": "Модели и данные", "affected_dimension": "data"},
        ),
    )

    assert len(question.options) == 2
    with pytest.raises(ValidationError):
        DecisionRefinementQuestion(
            id="question:too-many",
            prompt="Выберите",
            candidate_program_ids=(PROGRAM_A,),
            options=question.options,
        )


def test_timestamps_are_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        DecisionState.model_validate(
            {
                **_state().model_dump(),
                "updated_at": datetime.now(),
            },
        )

    with pytest.raises(ValidationError):
        DecisionState(created_at=NOW, updated_at=NOW - timedelta(seconds=1))
