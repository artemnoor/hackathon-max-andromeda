"""Application service composing conversation, policies and existing engines."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
    AdmissionBenefitPolicyEvaluation,
    AdmissionBenefitPolicyEvaluationRequest,
    AdmissionBenefitPolicyEvaluationStatus,
    AdmissionBenefitPolicyRuleRef,
    ApplicantAdmissionContext,
)
from andromeda.modules.admission_fit.contracts.public import AdmissionFitSearchGateway
from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.modules.analytics.services.executor import AnalyticsExecutor
from andromeda.modules.conversation.contracts.assistant import (
    AssistantPolicyAnswer,
    AssistantResult,
    AssistantState,
    PolicyAnswerStatus,
)
from andromeda.modules.conversation.contracts.policy import (
    DecisionAction,
    DecisionPolicyPort,
)
from andromeda.modules.conversation.contracts.ports import (
    AdmissionBenefitPolicyEvaluator,
    KnowledgeClaimLookupReader,
    PolicyQueryResolver,
    QuerySessionRepository,
)
from andromeda.modules.conversation.contracts.public import (
    AdmissionUniversityScope,
    ConversationIntent,
    ConversationSlot,
    FactOrigin,
    NextAction,
    PolicyQueryFocus,
    QueryFact,
    QuerySession,
    QuerySessionId,
)
from andromeda.modules.entity_resolution.contracts.ports import EntityResolverGateway
from andromeda.modules.entity_resolution.contracts.public import (
    ResolutionContext,
    ResolutionEntityType,
    ResolutionStatus,
)
from andromeda.modules.knowledge.contracts.public import (
    ClaimReviewState,
    ClaimRevisionRef,
    KnowledgeClaimLookup,
)
from andromeda.modules.policy.contracts.applicability import (
    PolicyApplicabilityContext,
    PolicyContextAvailability,
    PolicyContextOrigin,
    PolicyContextValue,
)
from andromeda.modules.policy.contracts.resolution import (
    PolicyResolutionRequest,
    PolicyResolutionStatus,
    ResolutionTrace,
)
from andromeda.modules.policy.contracts.rule import PolicyDomainOwner
from andromeda.modules.policy.contracts.rule_ast import PolicyContextField
from andromeda.modules.presentation.contracts.envelope import ResponseEnvelope
from andromeda.modules.presentation.contracts.policy import (
    ResponseFormat,
    ResponsePolicyPort,
    ResponseRequest,
)
from andromeda.modules.presentation.contracts.verbalization import (
    ResponseVerbalizerPort,
)
from andromeda.modules.presentation.services.envelope_builder import (
    build_response_envelope,
)
from andromeda.modules.presentation.services.knowledge_response import (
    KnowledgeResponseRenderer,
)
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.shared.contracts.errors import ContractError, ErrorCode, NotFoundError
from andromeda.shared.contracts.ids import ProgramId

from .engine import ConversationEngine
from .policy_presentation import project_policy_answer
from .query_compiler import compile_session

logger = logging.getLogger("andromeda.conversation.assistant")


class AssistantService:
    def __init__(
        self,
        sessions: QuerySessionRepository,
        conversation: ConversationEngine,
        decision_policy: DecisionPolicyPort,
        response_policy: ResponsePolicyPort,
        analytics: AnalyticsExecutor,
        admission_fit: AdmissionFitSearchGateway,
        programs: ProgramReader,
        *,
        entity_resolver: EntityResolverGateway | None = None,
        policy_resolver: PolicyQueryResolver | None = None,
        claim_lookup: KnowledgeClaimLookupReader | None = None,
        admission_benefit_policy_evaluator: AdmissionBenefitPolicyEvaluator
        | None = None,
        knowledge_verbalizer: ResponseVerbalizerPort | None = None,
        knowledge_policy_enabled: bool = False,
        ttl_seconds: int = 86_400,
    ) -> None:
        self._sessions = sessions
        self._conversation = conversation
        self._decision_policy = decision_policy
        self._response_policy = response_policy
        self._analytics = analytics
        self._admission_fit = admission_fit
        self._programs = programs
        self._entity_resolver = entity_resolver
        self._policy_resolver = policy_resolver
        self._claim_lookup = claim_lookup
        self._admission_benefit_policy_evaluator = admission_benefit_policy_evaluator
        self._knowledge_policy_enabled = knowledge_policy_enabled
        self._knowledge_response_renderer = KnowledgeResponseRenderer(
            knowledge_verbalizer
        )
        self._ttl_seconds = ttl_seconds

    def handle(
        self,
        text: str,
        *,
        owner_scope: ProfileScope,
        session_id: QuerySessionId | None = None,
        expected_revision: int | None = None,
        applicant_admission_context: ApplicantAdmissionContext | None = None,
        now: datetime | None = None,
    ) -> AssistantResult:
        timestamp = now or datetime.now(UTC)
        existing = (
            self._sessions.get(session_id, owner_scope=owner_scope)
            if session_id is not None
            else None
        )
        if session_id is not None and existing is None:
            raise NotFoundError(
                "Query session was not found or belongs to another owner"
            )
        session = existing or _new_session(owner_scope, timestamp, self._ttl_seconds)
        base_revision = session.revision if existing is not None else None
        updated = self._conversation.apply(
            session, text, expected_revision=expected_revision, now=timestamp
        )
        if applicant_admission_context is not None:
            updated = updated.model_copy(
                update={"applicant_admission_context": applicant_admission_context}
            )
        updated = self._resolve_entities(updated)
        decision = self._decision_policy.decide(updated)
        if decision.action is DecisionAction.ASK_CLARIFICATION:
            updated = updated.model_copy(update={"last_question": decision.question})
            self._save(updated, base_revision)
            return AssistantResult(
                state=AssistantState.NEEDS_CLARIFICATION,
                session_id=updated.session_id,
                revision=updated.revision,
                question=decision.question,
                options=decision.options,
                missing_slots=updated.missing_slots,
            )
        if updated.intent is ConversationIntent.KNOWLEDGE_POLICY_QUERY:
            return self._handle_policy_query(updated, base_revision, timestamp, text)
        candidate_program_ids = self._candidate_program_ids(updated)
        if (
            updated.intent is ConversationIntent.ADMISSION_SEARCH
            and candidate_program_ids
        ):
            updated = self._apply_admission_defaults(updated, candidate_program_ids)
        compiled = compile_session(updated, candidate_program_ids=candidate_program_ids)
        if updated.intent is ConversationIntent.ADMISSION_SEARCH:
            logger.info(
                "assistant_admission_scope_resolved scope=%s candidate_count=%d batch_count=%d",
                updated.admission_university_scope.value
                if updated.admission_university_scope
                else "selected_university",
                len(candidate_program_ids),
                len(compiled.admission_requests),
            )
        if compiled.analytics_query is not None:
            result = self._analytics.execute(compiled.analytics_query)
            updated = updated.model_copy(
                update={"last_query": compiled.analytics_query}
            )
            self._save(updated, base_revision)
            response_policy = self._response_policy.choose(
                ResponseRequest(
                    result=result,
                    comparison_requested=decision.action is DecisionAction.COMPARE,
                )
            )
            envelope = build_response_envelope(
                result,
                response_policy,
                text=f"Найдено результатов: {len(result.rows)}",
                result_reference=updated.session_id,
                metadata={"resolution_evidence": updated.frame.resolution_evidence},
            )
            return AssistantResult(
                state=AssistantState.COMPLETE,
                session_id=updated.session_id,
                revision=updated.revision,
                response=envelope,
                query=compiled.analytics_query,
            )
        if compiled.admission_requests:
            admission_result = self._admission_fit.evaluate_batches(
                compiled.admission_requests
            )
            updated = updated.model_copy(update={"last_query": None})
            self._save(updated, base_revision)
            selected = compiled.admission_requests[0]
            default_year = updated.inferred_parameters.get("admission_year")
            default_form = updated.inferred_parameters.get("study_form")
            year_text = (
                f"{selected.admission_year} (последний опубликованный год)"
                if default_year is not None and selected.admission_year is not None
                else str(selected.admission_year)
                if selected.admission_year is not None
                else "подходящий опубликованный год не найден"
            )
            form_text = _study_form_label(selected.study_form)
            if default_form is not None:
                form_text += " (по умолчанию)"
            funding_text = _funding_label(selected.funding_type)
            assumptions = tuple(
                assumption
                for assumption in (
                    f"Год приёма: {year_text}" if default_year is not None else None,
                    f"Форма обучения: {form_text}"
                    if default_form is not None
                    else None,
                )
                if assumption is not None
            )
            logger.info(
                "assistant_admission_filters_resolved candidate_count=%d admission_year=%s study_form=%s funding_type=%s defaulted_year=%s defaulted_form=%s",
                len(candidate_program_ids),
                selected.admission_year
                if selected.admission_year is not None
                else "unavailable",
                selected.study_form.value
                if selected.study_form is not None
                else "unknown",
                selected.funding_type.value
                if selected.funding_type is not None
                else "unknown",
                default_year is not None,
                default_form is not None,
            )
            envelope = ResponseEnvelope(
                response_type=ResponseFormat.TEXT,
                template="admission-fit-summary",
                text=(
                    f"Проверено программ: {len(admission_result.by_program_id)}. "
                    f"Параметры: год приёма — {year_text}; форма — {form_text}; финансирование — {funding_text}."
                ),
                data={"outcomes": admission_result.model_dump(mode="json")},
                metadata={
                    "admission_year": selected.admission_year,
                    "study_form": selected.study_form.value
                    if selected.study_form is not None
                    else None,
                    "funding_type": selected.funding_type.value
                    if selected.funding_type is not None
                    else None,
                    "assumptions": assumptions,
                },
                result_reference=updated.session_id,
            )
            return AssistantResult(
                state=AssistantState.COMPLETE,
                session_id=updated.session_id,
                revision=updated.revision,
                response=envelope,
                admission_request=compiled.admission_request,
                admission_requests=compiled.admission_requests,
                admission_result=admission_result,
            )
        raise ContractError(
            ErrorCode.INSUFFICIENT_DATA,
            "Admission search has no bounded candidate programs",
        )

    def _handle_policy_query(
        self,
        session: QuerySession,
        base_revision: int | None,
        now: datetime,
        query_text: str,
    ) -> AssistantResult:
        context = session.policy_query_context
        if context is None:
            raise ContractError(
                ErrorCode.INVALID_QUERY, "Policy query context is missing"
            )
        if not self._knowledge_policy_enabled:
            answer = AssistantPolicyAnswer(
                focus=context.focus,
                status=PolicyAnswerStatus.OUTSIDE_COVERAGE,
                reason_code="knowledge_policy_assistant_disabled",
            )
            return self._policy_answer_result(session, base_revision, answer)
        if (
            context.focus is PolicyQueryFocus.HISTORY
            and context.as_known_at is None
            and "вчера" in query_text.casefold()
        ):
            yesterday = now.astimezone(UTC).date() - timedelta(days=1)
            context = context.model_copy(
                update={
                    "as_known_at": datetime.combine(yesterday, time.max, tzinfo=UTC)
                }
            )
            session = session.model_copy(update={"policy_query_context": context})
        if context.claim_predicate is None or self._claim_lookup is None:
            answer = AssistantPolicyAnswer(
                focus=context.focus,
                status=PolicyAnswerStatus.OUTSIDE_COVERAGE,
                reason_code=(
                    "policy_topic_not_registered"
                    if context.claim_predicate is None
                    else "structured_claim_lookup_not_connected"
                ),
            )
            return self._policy_answer_result(
                session,
                base_revision,
                answer,
            )

        source_claims = self._claim_lookup.list_by_predicate(
            context.claim_predicate,
            as_known_at=context.as_known_at or now,
            limit=20,
        )
        if not source_claims:
            historical_unavailable = (
                context.focus is PolicyQueryFocus.HISTORY
                and context.as_known_at is not None
            )
            answer = AssistantPolicyAnswer(
                focus=context.focus,
                status=(
                    PolicyAnswerStatus.HISTORICAL_STATE_UNAVAILABLE
                    if historical_unavailable
                    else PolicyAnswerStatus.NO_MATCH
                ),
                reason_code=(
                    "historical_state_unavailable_at_requested_cutoff"
                    if historical_unavailable
                    else "no_source_claim_matched_registered_predicate"
                ),
            )
            return self._policy_answer_result(
                session,
                base_revision,
                answer,
            )

        source_status = _source_claim_answer_status(source_claims)
        is_cycle_comparison = bool(context.comparison_admission_years)
        comparison_years: tuple[int, int] | None = None
        if is_cycle_comparison:
            if len(context.comparison_admission_years) != 2:
                raise ContractError(
                    ErrorCode.INVALID_QUERY,
                    "Policy history comparison requires exactly two admission years",
                )
            comparison_years = (
                context.comparison_admission_years[0],
                context.comparison_admission_years[1],
            )
        is_historical_cycle = (
            context.focus is PolicyQueryFocus.HISTORY
            and context.mentioned_effective_year is not None
        )
        if (
            context.focus
            not in {
                PolicyQueryFocus.APPLICABILITY,
                PolicyQueryFocus.IMPACT,
            }
            and not is_cycle_comparison
            and not is_historical_cycle
        ):
            answer = AssistantPolicyAnswer(
                focus=context.focus,
                status=source_status,
                source_claims=source_claims,
                reason_code=source_status.value,
            )
            return self._policy_answer_result(
                session,
                base_revision,
                answer,
            )
        if source_status is not PolicyAnswerStatus.SOURCE_ASSERTIONS_FOUND:
            answer = AssistantPolicyAnswer(
                focus=context.focus,
                status=source_status,
                source_claims=source_claims,
                reason_code=source_status.value,
            )
            return self._policy_answer_result(
                session,
                base_revision,
                answer,
            )

        university_ids = tuple(
            session.entities.get(ResolutionEntityType.UNIVERSITY, ())
        )
        if len(university_ids) != 1:
            return self._ask_policy_university(session, base_revision)
        year_fact = session.confirmed_parameters.get("admission_year")
        if context.focus in {PolicyQueryFocus.APPLICABILITY, PolicyQueryFocus.IMPACT}:
            if (
                year_fact is None
                or year_fact.origin is not FactOrigin.EXPLICIT_USER
                or not year_fact.confirmed
                or type(year_fact.value) is not int
            ):
                raise ContractError(
                    ErrorCode.INSUFFICIENT_DATA,
                    "Policy applicability requires an explicit admission year",
                )
            admission_year = year_fact.value
        elif is_cycle_comparison:
            assert comparison_years is not None
            admission_year = comparison_years[0]
        elif context.mentioned_effective_year is not None:
            admission_year = context.mentioned_effective_year.year
        else:
            answer = AssistantPolicyAnswer(
                focus=context.focus,
                status=source_status,
                source_claims=source_claims,
                reason_code="historical_source_state_without_admission_cycle",
            )
            return self._policy_answer_result(session, base_revision, answer)
        if self._policy_resolver is None:
            answer = AssistantPolicyAnswer(
                focus=context.focus,
                status=PolicyAnswerStatus.INDETERMINATE,
                source_claims=source_claims,
                reason_code="policy_resolver_not_composed",
            )
            return self._policy_answer_result(
                session,
                base_revision,
                answer,
            )

        request = PolicyResolutionRequest(
            university_id=university_ids[0],
            admission_year=admission_year,
            context=_policy_applicability_context(session),
            valid_as_of=context.valid_as_of,
            as_known_at=context.as_known_at or now,
        )
        claim_refs = tuple(
            ClaimRevisionRef(
                claim_id=item.claim.claim_id,
                revision=item.claim.clock.revision,
            )
            for item in source_claims
            if item.claim.review_state is ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION
        )
        comparison = (
            self._policy_resolver.compare_for_claims(
                request,
                comparison_years,
                claim_refs,
            )
            if comparison_years is not None
            else None
        )
        trace = (
            comparison.after_trace
            if comparison is not None
            else self._policy_resolver.resolve_for_admission_cycle(request, claim_refs)
            if is_historical_cycle
            else self._policy_resolver.resolve_for_claims(request, claim_refs)
        )

        status = {
            PolicyResolutionStatus.RESOLVED: PolicyAnswerStatus.RESOLVED,
            PolicyResolutionStatus.CONFLICT: PolicyAnswerStatus.CONFLICT,
            PolicyResolutionStatus.NO_MATCH: PolicyAnswerStatus.NO_MATCH,
            PolicyResolutionStatus.BLOCKED_BY_MISSING_DATA: PolicyAnswerStatus.BLOCKED_BY_MISSING_DATA,
            PolicyResolutionStatus.INDETERMINATE: PolicyAnswerStatus.INDETERMINATE,
            PolicyResolutionStatus.CANDIDATES_FOUND: PolicyAnswerStatus.INDETERMINATE,
        }[trace.status]
        if trace.status is PolicyResolutionStatus.NO_MATCH and source_claims:
            status = PolicyAnswerStatus.SOURCE_ASSERTIONS_FOUND
        domain_evaluation = None
        missing_input_codes: tuple[str, ...] = ()
        reason_code = trace.status.value
        if (
            context.focus is PolicyQueryFocus.IMPACT
            and status is PolicyAnswerStatus.RESOLVED
        ):
            domain_evaluation = self._evaluate_admission_benefit_impact(session, trace)
            if (
                domain_evaluation.status
                is not AdmissionBenefitPolicyEvaluationStatus.EVALUATED
            ):
                status = PolicyAnswerStatus.POLICY_RESOLVED_DOMAIN_RESULT_UNAVAILABLE
                missing_input_codes = domain_evaluation.missing_input_codes
                reason_code = (
                    missing_input_codes[0]
                    if missing_input_codes
                    else "admission_benefit_domain_result_unavailable"
                )
            else:
                reason_code = "admission_benefit_domain_evaluation_complete"
        answer = AssistantPolicyAnswer(
            focus=context.focus,
            status=status,
            resolution_trace=trace,
            cycle_comparison=comparison,
            domain_evaluation=domain_evaluation,
            source_claims=source_claims,
            reason_code=reason_code,
            missing_input_codes=missing_input_codes,
        )
        updated = session.model_copy(
            update={
                "policy_query_context": context.model_copy(
                    update={"resolution_trace_id": trace.trace_id}
                )
            }
        )
        return self._policy_answer_result(
            updated,
            base_revision,
            answer,
        )

    def _evaluate_admission_benefit_impact(
        self, session: QuerySession, trace: ResolutionTrace
    ) -> AdmissionBenefitPolicyEvaluation:
        evaluator = self._admission_benefit_policy_evaluator
        if evaluator is None:
            return _unavailable_benefit_evaluation(
                "admission_benefit_domain_evaluator_not_composed"
            )

        program_ids = tuple(session.entities.get(ResolutionEntityType.PROGRAM, ()))
        if len(program_ids) != 1:
            return _unavailable_benefit_evaluation(
                "target_program_missing_or_ambiguous"
            )
        program = self._programs.get(program_ids[0])
        if program is None:
            return _unavailable_benefit_evaluation("target_program_unavailable")
        expected_direction_prefix = (
            f"direction:{trace.university_id.removeprefix('university:')}:"
        )
        if not program.direction_id.startswith(expected_direction_prefix):
            return _unavailable_benefit_evaluation("target_program_university_mismatch")

        owner_refs = tuple(
            selection.domain_rule
            for selection in trace.effective_rules
            if selection.domain_rule.owner_module
            is PolicyDomainOwner.ADMISSION_BENEFITS
        )
        if not owner_refs:
            return _unavailable_benefit_evaluation(
                "effective_policy_has_no_admission_benefit_owner_rules"
            )
        if len(owner_refs) != len(trace.effective_rules):
            return _unavailable_benefit_evaluation(
                "mixed_domain_owners_require_separate_impact_evaluations"
            )

        selected_rules: list[AdmissionBenefitPolicyRuleRef] = []
        selected_individual_policy_id: str | None = None
        selected_individual_policy_hash: str | None = None
        unsupported: list[str] = []
        for reference in owner_refs:
            if reference.owner_revision_hash is None:
                unsupported.append("exact_domain_owner_revision_hash_missing")
            elif reference.canonical_rule_id.startswith("admission-benefit:"):
                selected_rules.append(
                    AdmissionBenefitPolicyRuleRef(
                        rule_id=reference.canonical_rule_id,
                        revision_hash=reference.owner_revision_hash,
                    )
                )
            elif reference.canonical_rule_id.startswith("individual-achievement:"):
                if selected_individual_policy_id is not None:
                    unsupported.append(
                        "multiple_individual_achievement_policies_selected"
                    )
                selected_individual_policy_id = reference.canonical_rule_id
                selected_individual_policy_hash = reference.owner_revision_hash
            else:
                unsupported.append("unsupported_admission_benefit_domain_rule_kind")
        if unsupported:
            return _unavailable_benefit_evaluation(*unsupported)

        try:
            return evaluator.evaluate(
                AdmissionBenefitPolicyEvaluationRequest(
                    university_id=trace.university_id,
                    program_id=program.id,
                    direction_code=program.direction_id.rsplit(":", 1)[-1],
                    admission_year=trace.admission_year,
                    applicant=session.applicant_admission_context
                    or ApplicantAdmissionContext(),
                    selected_rules=tuple(selected_rules),
                    selected_individual_policy_id=selected_individual_policy_id,
                    selected_individual_policy_hash=selected_individual_policy_hash,
                )
            )
        except Exception:
            logger.exception(
                "assistant_policy_domain_evaluation_rejected trace_id=%s",
                trace.trace_id,
            )
            return _unavailable_benefit_evaluation(
                "admission_benefit_domain_evaluation_contract_rejected"
            )

    def _ask_policy_university(
        self,
        session: QuerySession,
        base_revision: int | None,
    ) -> AssistantResult:
        missing = (ConversationSlot.ENTITY,)
        updated = session.model_copy(
            update={
                "missing_slots": missing,
                "next_action": NextAction.ASK_FOR_ENTITY,
                "last_action": NextAction.ASK_FOR_ENTITY,
                "frame": session.frame.model_copy(update={"missing_fields": missing}),
            }
        )
        question = "Для какого вуза проверить правило?"
        updated = updated.model_copy(update={"last_question": question})
        self._save(updated, base_revision)
        return AssistantResult(
            state=AssistantState.NEEDS_CLARIFICATION,
            session_id=updated.session_id,
            revision=updated.revision,
            question=question,
            missing_slots=missing,
        )

    def _policy_answer_result(
        self,
        session: QuerySession,
        base_revision: int | None,
        answer: AssistantPolicyAnswer,
    ) -> AssistantResult:
        self._save(session, base_revision)
        query_context = session.policy_query_context
        knowledge = project_policy_answer(
            answer,
            focus=query_context.focus if query_context else PolicyQueryFocus.STATUS,
            as_known_at=(
                (query_context.as_known_at or session.updated_at)
                if query_context
                else session.updated_at
            ),
        )
        rendered = self._knowledge_response_renderer.render(
            knowledge,
            unverified_fallback=(answer.status is PolicyAnswerStatus.OUTSIDE_COVERAGE),
        )
        response = ResponseEnvelope(
            response_type=ResponseFormat.TEXT,
            response_mode=rendered.response_mode,
            template="policy-resolution",
            text=rendered.text,
            knowledge=knowledge,
            metadata={
                "knowledge_state": answer.status.value,
                "resolution_trace_id": (
                    answer.resolution_trace.trace_id
                    if answer.resolution_trace
                    else None
                ),
            },
            result_reference=session.session_id,
        )
        return AssistantResult(
            state=AssistantState.COMPLETE,
            session_id=session.session_id,
            revision=session.revision,
            response=response,
            policy_answer=answer,
        )

    def _resolve_entities(self, session: QuerySession) -> QuerySession:
        if self._entity_resolver is None:
            return session
        resolved = {key: tuple(values) for key, values in session.entities.items()}
        resolution_cache = dict(session.resolution_cache)
        resolution_evidence = dict(session.frame.resolution_evidence)
        unresolved: list[str] = []
        for entity_type in (
            ResolutionEntityType.UNIVERSITY,
            ResolutionEntityType.DIRECTION,
            ResolutionEntityType.PROGRAM,
        ):
            queries = tuple(resolved.get(entity_type, ()))
            if not queries:
                continue
            selected: list[str] = []
            university_ids = tuple(resolved.get(ResolutionEntityType.UNIVERSITY, ()))
            context_university = (
                university_ids[0]
                if len(university_ids) == 1
                and university_ids[0].startswith("university:")
                else None
            )
            context = (
                ResolutionContext(university_id=context_university)
                if context_university
                else None
            )
            for query in queries:
                cache_key = f"{entity_type.value}:{query}"
                cached_id = resolution_cache.get(cache_key)
                if cached_id:
                    selected.append(cached_id)
                    resolution_evidence[cache_key] = (
                        "strategy=deterministic;source=session_cache"
                    )
                    continue
                result = self._entity_resolver.resolve(
                    entity_type, query, context=context, limit=10
                )
                if (
                    result.resolution_strategy == "deterministic"
                    and result.status
                    in {ResolutionStatus.EXACT, ResolutionStatus.RESOLVED}
                    and result.selected_id
                ):
                    selected.append(result.selected_id)
                    resolution_cache[cache_key] = result.selected_id
                    resolution_evidence[cache_key] = (
                        f"strategy={result.resolution_strategy};candidate_hash={result.candidate_hash or 'none'}"
                    )
                else:
                    unresolved.append(f"{entity_type.value}:{query}")
                    resolution_evidence[cache_key] = (
                        f"strategy={result.resolution_strategy};candidate_hash={result.candidate_hash or 'none'}"
                    )
            if selected:
                resolved[entity_type] = tuple(dict.fromkeys(selected))
        if not unresolved:
            return session.model_copy(
                update={
                    "entities": resolved,
                    "resolution_cache": resolution_cache,
                    "unresolved_entities": (),
                    "frame": session.frame.model_copy(
                        update={
                            "entities": resolved,
                            "resolution_evidence": resolution_evidence,
                        }
                    ),
                }
            )
        university_unresolved = any(
            item.startswith("university:") for item in unresolved
        )
        next_action = (
            NextAction.ASK_FOR_UNIVERSITY_SCOPE
            if university_unresolved
            else NextAction.ASK_FOR_ENTITY
        )
        missing = (
            (ConversationSlot.UNIVERSITY_SCOPE,)
            if university_unresolved
            else (ConversationSlot.ENTITY,)
        )
        return session.model_copy(
            update={
                "entities": resolved,
                "resolution_cache": resolution_cache,
                "unresolved_entities": tuple(unresolved),
                "missing_slots": missing,
                "next_action": next_action,
                "last_action": next_action,
                "frame": session.frame.model_copy(
                    update={
                        "entities": resolved,
                        "missing_fields": missing,
                        "resolution_evidence": resolution_evidence,
                    }
                ),
            }
        )

    def _candidate_program_ids(self, session: QuerySession) -> tuple[ProgramId, ...]:
        programs = tuple(session.entities.get(ResolutionEntityType.PROGRAM, ()))
        if programs:
            return programs
        university_ids = tuple(
            session.entities.get(ResolutionEntityType.UNIVERSITY, ())
        )
        direction_ids = set(session.entities.get(ResolutionEntityType.DIRECTION, ()))
        if university_ids:
            values = tuple(
                program
                for university_id in university_ids
                for program in self._programs.list(university_id=university_id)
            )
            return tuple(
                program.id
                for program in values
                if not direction_ids or program.direction_id in direction_ids
            )
        if (
            session.admission_university_scope
            is AdmissionUniversityScope.ANY_UNIVERSITY
        ):
            values = self._programs.list()
            return tuple(
                program.id
                for program in values
                if not direction_ids or program.direction_id in direction_ids
            )
        if direction_ids:
            return tuple(
                program.id
                for program in self._programs.list()
                if program.direction_id in direction_ids
            )
        return ()

    def _apply_admission_defaults(
        self,
        session: QuerySession,
        candidate_program_ids: tuple[ProgramId, ...],
    ) -> QuerySession:
        funding_fact = session.confirmed_parameters.get("funding_type")
        if funding_fact is None or not isinstance(funding_fact.value, FundingType):
            return session

        inferred = dict(session.inferred_parameters)
        confirmed_form = session.confirmed_parameters.get("study_form")
        if confirmed_form is None or not isinstance(confirmed_form.value, StudyForm):
            study_form = StudyForm.FULL_TIME
            inferred["study_form"] = QueryFact(
                value=study_form,
                origin=FactOrigin.POLICY_DEFAULT,
                confirmed=False,
                source="admission_search_default",
            )
        else:
            study_form = confirmed_form.value
            inferred.pop("study_form", None)

        confirmed_year = session.confirmed_parameters.get("admission_year")
        if confirmed_year is None or not isinstance(confirmed_year.value, int):
            admission_year = self._admission_fit.latest_published_year(
                candidate_program_ids,
                study_form=study_form,
                funding_type=funding_fact.value,
            )
            inferred["admission_year"] = QueryFact(
                value=admission_year,
                origin=FactOrigin.POLICY_DEFAULT,
                confirmed=False,
                source="latest_published_admission_offering",
            )
        else:
            inferred.pop("admission_year", None)

        assumption_strings: list[str] = []
        if "admission_year" in inferred:
            year = inferred["admission_year"].value
            assumption_strings.append(
                f"Год приёма выбран по последним опубликованным данным: {year}"
                if isinstance(year, int)
                else "Подходящий опубликованный год приёма не найден"
            )
        if "study_form" in inferred:
            assumption_strings.append("Очная форма выбрана по умолчанию")
        return session.model_copy(
            update={
                "inferred_parameters": inferred,
                "assumptions": tuple(assumption_strings),
            }
        )

    def _save(self, session: QuerySession, base_revision: int | None) -> None:
        self._sessions.save(session, expected_revision=base_revision)


def _new_session(
    owner_scope: ProfileScope, now: datetime, ttl_seconds: int
) -> QuerySession:
    return QuerySession(
        session_id=f"query-session:{uuid4().hex}",
        owner_scope=owner_scope,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )


def _study_form_label(value: StudyForm | None) -> str:
    return {
        StudyForm.FULL_TIME: "очная",
        StudyForm.PART_TIME: "заочная",
        StudyForm.EVENING: "вечерняя",
        StudyForm.ONLINE: "онлайн",
        StudyForm.UNKNOWN: "неизвестная",
        None: "не указана",
    }[value]


def _funding_label(value: FundingType | None) -> str:
    return {
        FundingType.BUDGET: "бюджет",
        FundingType.PAID: "платное обучение",
        FundingType.TARGETED: "целевой набор",
        FundingType.UNKNOWN: "неизвестно",
        None: "не выбран",
    }[value]


def _policy_applicability_context(session: QuerySession) -> PolicyApplicabilityContext:
    values: list[PolicyContextValue] = []
    for entity_type, field in (
        (ResolutionEntityType.DIRECTION, PolicyContextField.DIRECTION_ID),
        (ResolutionEntityType.PROGRAM, PolicyContextField.PROGRAM_ID),
    ):
        entity_ids = tuple(session.entities.get(entity_type, ()))
        if len(entity_ids) == 1:
            values.append(
                PolicyContextValue(
                    field=field,
                    availability=PolicyContextAvailability.PRESENT,
                    origin=PolicyContextOrigin.USER_PROVIDED,
                    value=entity_ids[0],
                )
            )
        elif len(entity_ids) > 1:
            values.append(
                PolicyContextValue(
                    field=field,
                    availability=PolicyContextAvailability.UNKNOWN,
                    origin=PolicyContextOrigin.USER_PROVIDED,
                )
            )
    return PolicyApplicabilityContext(values=tuple(values))


def _unavailable_benefit_evaluation(
    *codes: str,
) -> AdmissionBenefitPolicyEvaluation:
    return AdmissionBenefitPolicyEvaluation(
        status=AdmissionBenefitPolicyEvaluationStatus.UNAVAILABLE,
        missing_input_codes=tuple(dict.fromkeys(codes)),
    )


def _source_claim_answer_status(
    source_claims: tuple[KnowledgeClaimLookup, ...],
) -> PolicyAnswerStatus:
    states = tuple(item.claim.review_state for item in source_claims)
    if ClaimReviewState.UNRESOLVED in states:
        return PolicyAnswerStatus.INDETERMINATE
    if any(
        state in {ClaimReviewState.UNREVIEWED, ClaimReviewState.NEEDS_REVIEW}
        for state in states
    ):
        return PolicyAnswerStatus.REVIEW_REQUIRED
    accepted = tuple(
        item.claim
        for item in source_claims
        if item.claim.review_state is ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION
    )
    if not accepted:
        return PolicyAnswerStatus.INDETERMINATE
    for index, left in enumerate(accepted):
        if left.proposition is None:
            continue
        for right in accepted[index + 1 :]:
            if right.proposition is None:
                continue
            same_subject = (
                left.proposition.subject_kind is right.proposition.subject_kind
                and left.proposition.subject_id == right.proposition.subject_id
            )
            if same_subject and left.proposition != right.proposition:
                return PolicyAnswerStatus.INDETERMINATE
    return PolicyAnswerStatus.SOURCE_ASSERTIONS_FOUND


__all__ = ["AssistantService"]
