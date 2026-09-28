"""Application service owning explicit decision mutations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import logging

from andromeda.modules.proftest.contracts.public import CurrentUserProfileReader, ProfileRefinement, ProfileScope, UserProfileRefinementWriter
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.shared.contracts.errors import AndromedaError, ConflictError, ContractError, ErrorCode, NotFoundError, ValidationError
from andromeda.shared.contracts.ids import ProgramId

from ..contracts.public import (
    DecisionConstraintsUpdate,
    DecisionContext,
    DecisionContextMetadata,
    DecisionContextResult,
    DecisionMutationResult,
    DecisionRefinementAnswer,
    DecisionRefinementResult,
    DecisionSuggestionsResult,
    ProgramCommand,
    ShortlistCommand,
    ShortlistRoleCommand,
)
from ..domain.entities import DecisionChoice, DecisionSnapshot, DecisionState
from ..domain.values import DecisionSourceKind
from ..repository.ports import DecisionContextRepository
from .candidates import DecisionCandidatePipeline
from .analytics import DecisionAnalyticsService


logger = logging.getLogger("andromeda.modules.decision.service")


class DecisionService:
    """Coordinate canonical reads, explicit choice transitions and persistence."""

    def __init__(
        self,
        repository: DecisionContextRepository,
        programs: ProgramReader,
        profiles: CurrentUserProfileReader,
        candidates: DecisionCandidatePipeline,
        *,
        ttl_seconds: int,
        clock: Callable[[], datetime] | None = None,
        analytics: DecisionAnalyticsService | None = None,
        profile_writer: UserProfileRefinementWriter | None = None,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self._repository = repository
        self._programs = programs
        self._profiles = profiles
        self._candidates = candidates
        self._ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._analytics = analytics
        self._profile_writer = profile_writer

    def get_context(self, scope: ProfileScope) -> DecisionContextResult:
        snapshot = self._load(scope)
        context = self._context(scope, snapshot)
        logger.info(
            "decision_context_complete operation=get_context owner_kind=%s revision=%d shortlist_count=%d",
            scope.owner_kind,
            snapshot.revision,
            len(snapshot.state.choice.active_shortlist),
        )
        return DecisionContextResult(decision_id=snapshot.decision_id, context=context)

    def get_suggestions(self, scope: ProfileScope) -> DecisionSuggestionsResult:
        context = self.get_context(scope).context
        result = self._candidates.build(context)
        logger.info(
            "decision_suggestions_complete owner_kind=%s revision=%d suggestion_count=%d",
            scope.owner_kind,
            result.context_revision,
            len(result.suggestions),
        )
        return result

    def answer_refinement(
        self,
        scope: ProfileScope,
        command: DecisionRefinementAnswer,
    ) -> DecisionRefinementResult:
        """Apply one current refinement option to preferences and re-rank.

        The question is read again immediately before the write.  This makes
        stale client revisions fail closed and guarantees that a refinement
        cannot mutate the explicit shortlist or decision revision.
        """

        if self._profile_writer is None:
            raise ValidationError("Profile refinement is not configured")
        profile = self._profiles.get_current(scope)
        if profile is None:
            raise NotFoundError("Current profile was not found")
        if profile.revision != command.expected_revision:
            logger.warning("decision_refinement_rejected outcome=stale_profile_revision")
            raise ConflictError("Current profile revision is stale")

        suggestions = self.get_suggestions(scope)
        question = suggestions.refinement_question
        if question is None or question.id != command.question_id:
            logger.warning("decision_refinement_rejected outcome=stale_question")
            raise ConflictError("The requested refinement question is no longer available")
        option = next((item for item in question.options if item.id == command.option_id), None)
        current_candidate_ids = {
            item.program_id
            for item in (*suggestions.primary_candidates, *suggestions.alternative_candidates)
        }
        if option is None or not set(question.candidate_program_ids).issubset(current_candidate_ids):
            logger.warning("decision_refinement_rejected outcome=stale_option")
            raise ConflictError("The requested refinement option is no longer available")

        updated_profile = self._profile_writer.apply_refinement(
            scope,
            ProfileRefinement(
                question_id=question.id,
                option_id=option.id,
                affected_dimension=option.affected_dimension,
            ),
            expected_revision=command.expected_revision,
        )
        refreshed = self.get_suggestions(scope)
        logger.info(
            "decision_refinement_complete profile_revision=%d candidate_count=%d context_revision=%d",
            updated_profile.revision,
            len(refreshed.suggestions),
            refreshed.context_revision,
        )
        return DecisionRefinementResult(suggestions=refreshed, profile_revision=updated_profile.revision)

    def update_constraints(
        self,
        scope: ProfileScope,
        command: DecisionConstraintsUpdate,
    ) -> DecisionMutationResult:
        return self._mutate(
            scope,
            expected_revision=command.expected_revision,
            operation="update_constraints",
            transition=lambda state, now: state.with_constraints(command.constraints, now=now),
        )

    def mark_considered(self, scope: ProfileScope, command: ProgramCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)
        return self._mutate_choice(
            scope,
            expected_revision=command.expected_revision,
            operation="mark_considered",
            program_id=command.program_id,
            transition=lambda choice, now: choice.consider(command.program_id),
        )

    def add_shortlist(self, scope: ProfileScope, command: ShortlistCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)

        def transition(choice: DecisionChoice, now: datetime) -> DecisionChoice:
            # Adding a shortlist item also records that it was considered;
            # both are explicit user actions represented by one state update.
            return choice.consider(command.program_id).add_shortlist(
                command.program_id,
                role=command.role,
                origin=DecisionSourceKind.USER,
                now=now,
            )

        return self._mutate_choice(
            scope,
            expected_revision=command.expected_revision,
            operation="add_shortlist",
            program_id=command.program_id,
            transition=transition,
        )

    def remove_shortlist(self, scope: ProfileScope, command: ProgramCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)
        return self._mutate_choice(
            scope,
            expected_revision=command.expected_revision,
            operation="remove_shortlist",
            program_id=command.program_id,
            transition=lambda choice, now: choice.remove_shortlist(command.program_id, now=now),
        )

    def restore_shortlist(self, scope: ProfileScope, command: ProgramCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)
        return self._mutate_choice(
            scope,
            expected_revision=command.expected_revision,
            operation="restore_shortlist",
            program_id=command.program_id,
            transition=lambda choice, now: choice.restore_shortlist(command.program_id, now=now),
        )

    def set_shortlist_role(self, scope: ProfileScope, command: ShortlistRoleCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)
        return self._mutate_choice(
            scope,
            expected_revision=command.expected_revision,
            operation="set_shortlist_role",
            program_id=command.program_id,
            transition=lambda choice, now: choice.set_role(command.program_id, role=command.role, now=now),
        )

    def select_final_choice(self, scope: ProfileScope, command: ProgramCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)
        return self._mutate(
            scope,
            expected_revision=command.expected_revision,
            operation="select_final_choice",
            program_id=command.program_id,
            transition=lambda state, now: state.select_final_choice(command.program_id, now=now),
        )

    def reopen_final_choice(self, scope: ProfileScope, *, expected_revision: int | None) -> DecisionMutationResult:
        return self._mutate(
            scope,
            expected_revision=expected_revision,
            operation="reopen_final_choice",
            transition=lambda state, now: state.reopen_final_choice(now=now),
        )

    def exclude_program(self, scope: ProfileScope, command: ProgramCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)
        return self._mutate_choice(
            scope,
            expected_revision=command.expected_revision,
            operation="exclude_program",
            program_id=command.program_id,
            transition=lambda choice, now: choice.exclude(command.program_id),
        )

    def restore_excluded_program(self, scope: ProfileScope, command: ProgramCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)
        return self._mutate_choice(
            scope,
            expected_revision=command.expected_revision,
            operation="restore_excluded_program",
            program_id=command.program_id,
            transition=lambda choice, now: choice.restore_excluded(command.program_id),
        )

    def accept_suggestion(self, scope: ProfileScope, command: ShortlistCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)
        suggestions = self.get_suggestions(scope)
        if command.program_id not in {item.program_id for item in suggestions.suggestions}:
            raise ConflictError("The requested decision suggestion is no longer available")

        def transition(choice: DecisionChoice, now: datetime) -> DecisionChoice:
            return choice.consider(command.program_id).add_shortlist(
                command.program_id,
                role=command.role,
                origin=DecisionSourceKind.SUGGESTION_ACCEPTED,
                now=now,
            )

        return self._mutate_choice(
            scope,
            expected_revision=command.expected_revision,
            operation="accept_suggestion",
            program_id=command.program_id,
            transition=transition,
        )

    def reject_suggestion(self, scope: ProfileScope, command: ProgramCommand) -> DecisionMutationResult:
        self._require_program(command.program_id)
        suggestions = self.get_suggestions(scope)
        if command.program_id not in {item.program_id for item in suggestions.suggestions}:
            raise ConflictError("The requested decision suggestion is no longer available")
        return self._mutate_choice(
            scope,
            expected_revision=command.expected_revision,
            operation="reject_suggestion",
            program_id=command.program_id,
            transition=lambda choice, now: choice.exclude(command.program_id),
        )

    def _mutate_choice(
        self,
        scope: ProfileScope,
        *,
        expected_revision: int | None,
        operation: str,
        program_id: ProgramId | None = None,
        transition: Callable[[DecisionChoice, datetime], DecisionChoice],
    ) -> DecisionMutationResult:
        def state_transition(state: DecisionState, now: datetime) -> DecisionState:
            choice = transition(state.choice, now)
            if choice == state.choice:
                return state
            return state.with_choice(choice, now=now)

        return self._mutate(
            scope,
            expected_revision=expected_revision,
            operation=operation,
            program_id=program_id,
            transition=state_transition,
        )

    def _mutate(
        self,
        scope: ProfileScope,
        *,
        expected_revision: int | None,
        operation: str,
        program_id: ProgramId | None = None,
        transition: Callable[[DecisionState, datetime], DecisionState],
    ) -> DecisionMutationResult:
        snapshot = self._load(scope)
        if expected_revision is not None and expected_revision != snapshot.revision:
            raise ConflictError("Current decision context revision is stale")
        now = self._now()
        try:
            state = transition(snapshot.state, now)
        except ValueError as exc:
            raise _domain_error(exc) from exc
        if state == snapshot.state:
            logger.debug("decision_mutation_complete operation=%s changed=false revision=%d", operation, snapshot.revision)
            return DecisionMutationResult(
                decision_id=snapshot.decision_id,
                context=self._context(scope, snapshot),
                changed=False,
            )
        try:
            saved = self._repository.save(
                scope,
                state,
                expected_revision=snapshot.revision,
                expires_at=self._expires_at(now),
            )
        except ConflictError:
            logger.warning("decision_mutation_rejected operation=%s outcome=stale_revision", operation)
            raise
        if self._analytics is not None:
            try:
                self._analytics.record_mutation(
                    scope,
                    operation=operation,
                    program_id=program_id,
                    before=snapshot.state,
                    after=saved.state,
                )
            except Exception as exc:  # defensive boundary for custom writers/adapters
                logger.warning(
                    "decision_analytics_mutation_failed operation=%s outcome=ignored error_type=%s",
                    operation,
                    type(exc).__name__,
                )
        context = self._context(scope, saved)
        logger.info(
            "decision_mutation_complete operation=%s changed=true owner_kind=%s revision=%d shortlist_count=%d",
            operation,
            scope.owner_kind,
            saved.revision,
            len(saved.state.choice.active_shortlist),
        )
        return DecisionMutationResult(decision_id=saved.decision_id, context=context, changed=True)

    def _load(self, scope: ProfileScope) -> DecisionSnapshot:
        snapshot = self._repository.get_current(scope)
        if snapshot is not None:
            return snapshot
        return self._repository.get_or_create(scope, expires_at=self._expires_at(self._now()))

    def _context(self, scope: ProfileScope, snapshot: DecisionSnapshot) -> DecisionContext:
        profile_snapshot = self._profiles.get_current(scope)
        profile = profile_snapshot.profile if profile_snapshot is not None else None
        profile_revision = profile_snapshot.revision if profile_snapshot is not None else None
        state = snapshot.state
        missing: list[str] = []
        if profile is None:
            missing.append("profile_preferences")
        if state.admission_constraints is None:
            missing.append("admission_constraints")
        return DecisionContext(
            decision_id=snapshot.decision_id,
            state=state,
            preferences=profile,
            profile_revision=profile_revision,
            missing_data=tuple(missing),
            metadata=DecisionContextMetadata(
                decision_id=snapshot.decision_id,
                revision=snapshot.revision,
                status=state.status,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
                profile_revision=profile_revision,
            ),
        )

    def _require_program(self, program_id: ProgramId) -> None:
        if self._programs.get(program_id) is None:
            raise NotFoundError("Program was not found")

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Decision service clock must be timezone-aware")
        return now

    def _expires_at(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self._ttl_seconds)


def _domain_error(error: ValueError) -> AndromedaError:
    message = str(error)
    if "not found" in message:
        return NotFoundError(message)
    return ValidationError(message)


__all__ = ["DecisionService"]
