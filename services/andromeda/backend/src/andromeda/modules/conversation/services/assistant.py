"""Application service composing conversation, policies and existing engines."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
    AdmissionBenefitPolicyEvaluation,
    AdmissionBenefitPolicyEvaluationRequest,
    AdmissionBenefitPolicyEvaluationStatus,
    AdmissionBenefitPolicyRuleRef,
    ApplicantAdmissionContext,
)
from andromeda.modules.admission_benefits.contracts.public import AdmissionBenefitRule
from andromeda.modules.admission_benefits.repository.ports import AdmissionBenefitReader
from andromeda.modules.admission_fit.contracts.public import AdmissionFitSearchGateway
from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.modules.admissions.repository.ports import AdmissionReader
from andromeda.modules.analytics.services.executor import AnalyticsExecutor
from andromeda.modules.conversation.contracts.assistant import (
    AssistantPolicyAnswer,
    AssistantResult,
    AssistantState,
    PolicyAnswerStatus,
)
from andromeda.modules.conversation.contracts.language import (
    AssistantClarificationRequest,
    AssistantEntityCandidate,
    AssistantQueryInterpretation,
    ConversationAssistantAIPort,
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
    ParsedQuery,
    PolicyQueryFocus,
    PolicyQueryYear,
    ProgramDiscoveryContext,
    QueryFact,
    QuerySession,
    QuerySessionId,
)
from andromeda.modules.conversation.services.program_preferences import (
    extract_explicit_area_preferences,
)
from andromeda.modules.conversation.services.rule_parser import (
    remove_entity_name_metrics,
)
from andromeda.modules.curricula.repository.ports import CurriculumReader
from andromeda.modules.disciplines.contracts.public import area_definition
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
from andromeda.modules.presentation.contracts.envelope import (
    ResponseAction,
    ResponseActionItem,
    ResponseEnvelope,
)
from andromeda.modules.presentation.contracts.knowledge_response import ResponseMode
from andromeda.modules.presentation.contracts.policy import (
    ResponseFormat,
    ResponsePolicyPort,
    ResponseRequest,
)
from andromeda.modules.presentation.contracts.verbalization import (
    ResponseNaturalizerPort,
    ResponseVerbalizerPort,
)
from andromeda.modules.presentation.services.envelope_builder import (
    build_response_envelope,
)
from andromeda.modules.presentation.services.knowledge_response import (
    KnowledgeResponseRenderer,
)
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.proftest.repository.ports import ExplicitPreferenceProfileBuilder
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.modules.recommendations.contracts.public import (
    RecommendationCatalogReader,
    RecommendationRequest,
    RecommendationServicePort,
)
from andromeda.modules.universities.repository.ports import UniversityReader
from andromeda.shared.contracts.errors import ContractError, ErrorCode, NotFoundError
from andromeda.shared.contracts.ids import ProgramId

from ..domain.session import add_bounded_catalog_selection
from .ai_interpretation import (
    clarification_is_grounded,
    is_explicit_any_other_request,
    merge_ai_interpretation,
    safe_unverified_answer,
)
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
        curricula: CurriculumReader | None = None,
        admissions: AdmissionReader | None = None,
        admission_benefits: AdmissionBenefitReader | None = None,
        entity_resolver: EntityResolverGateway | None = None,
        policy_resolver: PolicyQueryResolver | None = None,
        claim_lookup: KnowledgeClaimLookupReader | None = None,
        admission_benefit_policy_evaluator: AdmissionBenefitPolicyEvaluator
        | None = None,
        knowledge_verbalizer: ResponseVerbalizerPort | None = None,
        knowledge_naturalizer: ResponseNaturalizerPort | None = None,
        conversation_ai: ConversationAssistantAIPort | None = None,
        recommendation_service: RecommendationServicePort | None = None,
        recommendation_catalog: RecommendationCatalogReader | None = None,
        explicit_preference_profile_builder: ExplicitPreferenceProfileBuilder | None = None,
        universities: UniversityReader | None = None,
        allowed_metric_codes: tuple[str, ...] = (),
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
        self._curricula = curricula
        self._admissions = admissions
        self._admission_benefits = admission_benefits
        self._entity_resolver = entity_resolver
        self._policy_resolver = policy_resolver
        self._claim_lookup = claim_lookup
        self._admission_benefit_policy_evaluator = admission_benefit_policy_evaluator
        self._knowledge_policy_enabled = knowledge_policy_enabled
        self._conversation_ai = conversation_ai
        self._recommendation_service = recommendation_service
        self._recommendation_catalog = recommendation_catalog
        self._explicit_preference_profile_builder = explicit_preference_profile_builder
        self._universities = universities
        self._allowed_metrics = allowed_metric_codes
        self._knowledge_response_renderer = KnowledgeResponseRenderer(
            knowledge_verbalizer, knowledge_naturalizer
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
        parsed_query = self._conversation.parse(text)
        ai_interpretation: AssistantQueryInterpretation | None = None
        ai_interpretation_attempted = False
        current_turn_is_clarification = bool(
            existing is not None
            and existing.missing_slots
            and existing.next_action is not NextAction.EXECUTE_QUERY
        )
        if self._conversation_ai is not None:
            ai_interpretation_attempted = True
            try:
                ai_interpretation = self._conversation_ai.interpret(
                    text,
                    current_intent=existing.intent if existing else None,
                    missing_slots=(
                        existing.missing_slots
                        if current_turn_is_clarification and existing
                        else ()
                    ),
                    known_entities=(
                        tuple(
                            entity_id
                            for values in existing.entities.values()
                            for entity_id in values
                        )[:12]
                        + tuple(
                            existing.program_discovery_context.candidate_program_ids[:8]
                            if existing.program_discovery_context
                            else ()
                        )
                        if existing
                        else ()
                    ),
                    allowed_metrics=(
                        self._allowed_metrics
                        if (
                            ConversationSlot.METRIC
                            in (
                                existing.missing_slots
                                if current_turn_is_clarification and existing
                                else ()
                            )
                            or (
                                parsed_query.intent
                                in {
                                    ConversationIntent.ANALYTICS_QUERY,
                                    ConversationIntent.COMPARE_PROGRAMS,
                                }
                                and not parsed_query.metric_codes
                            )
                        )
                        else ()
                    ),
                    rate_limit_key=owner_scope.owner_key,
                )
                parsed_query = merge_ai_interpretation(
                    parsed_query,
                    ai_interpretation,
                    text=text,
                    allowed_metrics=self._allowed_metrics,
                    current_intent=existing.intent if existing else None,
                    missing_slots=(
                        existing.missing_slots
                        if current_turn_is_clarification and existing
                        else ()
                    ),
                )
                logger.info(
                    "assistant_query_interpreted source=polza intent=%s entity_mentions=%d metric_count=%d",
                    parsed_query.intent.value,
                    len(ai_interpretation.entities),
                    len(ai_interpretation.metric_codes),
                )
            except Exception as error:  # noqa: BLE001 - the deterministic parser remains the safe fallback.
                ai_interpretation = None
                logger.warning(
                    "assistant_query_interpretation_fallback error_type=%s",
                    type(error).__name__,
                )
        if parsed_query.intent in {
            ConversationIntent.PROGRAM_DETAILS,
            ConversationIntent.COMPARE_PROGRAMS,
        }:
            normalized_text = " " + " ".join(
                re.findall(r"\w+", text.casefold().replace("ё", "е"))
            ) + " "
            mentions = sorted(
                (
                    normalized_text.find(
                        " " + " ".join(
                            re.findall(r"\w+", program.name.casefold().replace("ё", "е"))
                        ) + " "
                    ),
                    program.id,
                )
                for program in self._programs.list()
            )
            mentioned_ids = tuple(
                program_id for position, program_id in mentions if position >= 0
            )
            required_count = (
                2 if parsed_query.intent is ConversationIntent.COMPARE_PROGRAMS else 1
            )
            if len(mentioned_ids) >= required_count:
                parsed_query = parsed_query.model_copy(
                    update={"program_queries": mentioned_ids}
                )
        parsed_query = _apply_contextual_follow_up(parsed_query, existing, text)
        if (
            current_turn_is_clarification
            and parsed_query.intent is ConversationIntent.UNKNOWN
            and not parsed_query.starts_new_task
            and text.rstrip().endswith("?")
            and len(text.split()) >= 3
            and not any(
                (
                    parsed_query.total_score is not None,
                    bool(parsed_query.exam_scores),
                    parsed_query.admission_year is not None,
                    bool(parsed_query.university_queries),
                    bool(parsed_query.direction_queries),
                    bool(parsed_query.program_queries),
                    bool(parsed_query.metric_codes),
                    parsed_query.funding_type is not None,
                    parsed_query.study_form is not None,
                )
            )
        ):
            parsed_query = parsed_query.model_copy(update={"starts_new_task": True})
        if (
            existing is not None
            and parsed_query.intent is not ConversationIntent.UNKNOWN
            and parsed_query.intent is not existing.intent
        ):
            parsed_query = parsed_query.model_copy(update={"starts_new_task": True})
        session = existing or _new_session(owner_scope, timestamp, self._ttl_seconds)
        base_revision = session.revision if existing is not None else None
        if existing is not None and parsed_query.starts_new_task:
            session = _restart_session(existing, clear_task_facts=True)
        has_current_revision = (
            existing is not None
            and (
                expected_revision is None
                or expected_revision == existing.revision
            )
        )
        completed_session = (
            existing is not None
            and has_current_revision
            and existing.next_action is NextAction.EXECUTE_QUERY
            and not existing.missing_slots
        )
        incoming_intent = parsed_query.intent if completed_session else None
        if (
            completed_session
            and existing is not None
            and incoming_intent is ConversationIntent.UNKNOWN
        ):
            session = _restart_session(existing)
        comparison_question: str | None = None
        if (
            has_current_revision
            and existing is not None
            and session is existing
            and existing.intent is ConversationIntent.COMPARE_PROGRAMS
            and parsed_query.intent is ConversationIntent.COMPARE_PROGRAMS
            and existing.next_action
            in {NextAction.ASK_FOR_ENTITY, NextAction.ASK_FOR_METRIC}
            and existing.missing_slots
        ):
            session = _without_unresolved_comparison_inputs(existing)
            parsed_query, comparison_question = self._prepare_comparison_follow_up(
                session, text, parsed_query
            )
        updated = self._conversation.apply(
            session,
            text,
            parsed_query=parsed_query,
            expected_revision=expected_revision,
            now=timestamp,
        )
        if applicant_admission_context is not None:
            updated = updated.model_copy(
                update={"applicant_admission_context": applicant_admission_context}
            )
        updated = self._resolve_entities(updated)
        updated = self._apply_comparison_defaults(updated)
        alternative_catalog_unavailable = False
        alternative_options: tuple[str, ...] = ()
        if (
            ai_interpretation is not None
            and ai_interpretation.compare_with_any_other_direction
            and is_explicit_any_other_request(text)
            and updated.intent is ConversationIntent.COMPARE_PROGRAMS
            and ConversationSlot.ENTITY in updated.missing_slots
        ):
            (
                updated,
                alternative_catalog_unavailable,
                alternative_options,
            ) = self._select_other_direction(
                updated,
                text,
                rate_limit_key=owner_scope.owner_key,
            )
        decision = self._decision_policy.decide(updated)
        if (
            ai_interpretation is not None
            and (not current_turn_is_clarification or parsed_query.starts_new_task)
            and updated.intent is ConversationIntent.UNKNOWN
        ):
            answer = safe_unverified_answer(
                ai_interpretation.unverified_answer,
                user_message=text,
                intent=updated.intent,
                has_pending_slots=False,
            )
            if answer:
                updated = updated.model_copy(update={"last_question": None})
                self._save(updated, base_revision)
                response = ResponseEnvelope(
                    response_type=ResponseFormat.TEXT,
                    response_mode=ResponseMode.UNVERIFIED_FALLBACK,
                    template="assistant.unverified",
                    text=(
                        "⚠️ Общий ответ ИИ, не подтверждённый данными Andromeda.\n\n"
                        + answer
                    ),
                    result_reference=updated.session_id,
                )
                return AssistantResult(
                    state=AssistantState.COMPLETE,
                    session_id=updated.session_id,
                    revision=updated.revision,
                    response=response,
                )
        if decision.action is DecisionAction.ASK_CLARIFICATION:
            question = comparison_question or decision.question
            options = alternative_options or decision.options
            if alternative_catalog_unavailable:
                question = (
                    "В доступном каталоге этого вуза не нашла другое направление для сравнения. "
                    "Напишите другой вуз или название подходящей программы."
                )
            if (
                question
                and self._conversation_ai is not None
                and not ai_interpretation_attempted
            ):
                question = self._clarify_with_ai(
                    question,
                    updated,
                    text,
                    options,
                    rate_limit_key=owner_scope.owner_key,
                )
            updated = updated.model_copy(update={"last_question": question})
            self._save(updated, base_revision)
            return AssistantResult(
                state=AssistantState.NEEDS_CLARIFICATION,
                session_id=updated.session_id,
                revision=updated.revision,
                question=question,
                options=options,
                missing_slots=updated.missing_slots,
            )
        if updated.intent is ConversationIntent.KNOWLEDGE_POLICY_QUERY:
            return self._handle_policy_query(updated, base_revision, timestamp, text)
        if updated.intent is ConversationIntent.PROGRAM_DISCOVERY:
            return self._handle_program_discovery(
                updated, base_revision, timestamp, text
            )
        if updated.intent is ConversationIntent.PROGRAM_DETAILS:
            return self._handle_program_details(updated, base_revision)
        if updated.intent is ConversationIntent.OLYMPIAD_BENEFITS:
            return self._handle_olympiad_benefits(updated, base_revision)
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
            return self._naturalize_ordinary_result(
                AssistantResult(
                    state=AssistantState.COMPLETE,
                    session_id=updated.session_id,
                    revision=updated.revision,
                    response=envelope,
                    query=compiled.analytics_query,
                ),
                rate_limit_key=updated.owner_scope.owner_key,
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
            admission_outcomes = admission_result.model_dump(mode="json")
            serialized_programs = admission_outcomes.get("by_program_id")
            if isinstance(serialized_programs, dict):
                for program_id in admission_result.by_program_id:
                    program = self._programs.get(program_id)
                    outcome = serialized_programs.get(str(program_id))
                    if program is None or not isinstance(outcome, dict):
                        continue
                    serialized_result = outcome.get("result")
                    if isinstance(serialized_result, dict):
                        serialized_result["program_name"] = program.name
            envelope = ResponseEnvelope(
                response_type=ResponseFormat.TEXT,
                template="admission-fit-summary",
                text=(
                    (
                        "Нет, гарантировать поступление нельзя. Эта оценка основана "
                        "на доступных данных и не предсказывает будущий конкурс. "
                        "Решение принимает приёмная комиссия.\n\n"
                        if _is_admission_guarantee_question(text)
                        else ""
                    )
                    + f"Проверено программ: {len(admission_result.by_program_id)}. "
                    f"Параметры: год приёма — {year_text}; форма — {form_text}; финансирование — {funding_text}."
                ),
                data={"outcomes": admission_outcomes},
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
            if _is_admission_guarantee_question(text):
                return AssistantResult(
                    state=AssistantState.COMPLETE,
                    session_id=updated.session_id,
                    revision=updated.revision,
                    response=envelope,
                    admission_request=compiled.admission_request,
                    admission_requests=compiled.admission_requests,
                    admission_result=admission_result,
                )
            return self._naturalize_ordinary_result(
                AssistantResult(
                    state=AssistantState.COMPLETE,
                    session_id=updated.session_id,
                    revision=updated.revision,
                    response=envelope,
                    admission_request=compiled.admission_request,
                    admission_requests=compiled.admission_requests,
                    admission_result=admission_result,
                ),
                rate_limit_key=updated.owner_scope.owner_key,
            )
        raise ContractError(
            ErrorCode.INSUFFICIENT_DATA,
            "Admission search has no bounded candidate programs",
        )

    def _handle_program_discovery(
        self,
        session: QuerySession,
        base_revision: int | None,
        now: datetime,
        query_text: str,
    ) -> AssistantResult:
        context = session.program_discovery_context or ProgramDiscoveryContext()
        if not context.preferred_areas and not context.avoided_areas:
            raise ContractError(
                ErrorCode.INSUFFICIENT_DATA,
                "Program discovery requires a user-stated study preference",
            )
        if (
            self._recommendation_service is None
            or self._recommendation_catalog is None
            or self._explicit_preference_profile_builder is None
        ):
            answer_text = (
                "Подбор программ пока недоступен в этой конфигурации: "
                "сервис source-backed учебных планов не подключён."
            )
            self._save(session, base_revision)
            return AssistantResult(
                state=AssistantState.COMPLETE,
                session_id=session.session_id,
                revision=session.revision,
                response=ResponseEnvelope(
                    response_type=ResponseFormat.TEXT,
                    template="program-recommendations",
                    text=answer_text,
                    data={"recommendations": (), "status": "outside_coverage"},
                    metadata={"coverage": "unavailable"},
                    result_reference=session.session_id,
                ),
            )

        profile = self._explicit_preference_profile_builder.build_from_explicit_preferences(
            preferred_areas=context.preferred_areas,
            avoided_areas=context.avoided_areas,
        )
        fingerprints = self._recommendation_catalog.list_fingerprints()
        referenced_candidates = (
            set(context.candidate_program_ids)
            if context.candidate_program_ids
            and _is_discovery_candidate_reference(query_text)
            else None
        )
        university_ids = tuple(
            session.entities.get(ResolutionEntityType.UNIVERSITY, ())
        )
        selected_fingerprints = tuple(
            fingerprint
            for fingerprint in fingerprints
            if (referenced_candidates is None or fingerprint.program_id in referenced_candidates)
            and (
                not university_ids
                or any(
                    self._program_belongs_to_university(
                        fingerprint.program_id, university_id
                    )
                    for university_id in university_ids
                )
            )
        )
        ranked = self._recommendation_service.recommend_from_fingerprints(
            RecommendationRequest(profile=profile, limit=8), selected_fingerprints
        )
        supported = tuple(
            item
            for item in ranked.recommendations
            if item.evidence.catalog_completeness.value is not None
            and item.provenance
        )
        funding_fact = session.confirmed_parameters.get("funding_type")
        funding_filter = (
            funding_fact.value
            if funding_fact is not None and isinstance(funding_fact.value, FundingType)
            else None
        )
        matching_years: dict[ProgramId, tuple[int, ...]] = {}
        funding_sources: dict[str, dict[str, object]] = {}
        if funding_filter is not None:
            if self._admissions is None:
                supported = ()
            else:
                for item in supported:
                    offerings = self._admissions.get_for_program(item.program_id).offerings
                    matching_offerings = tuple(
                        offering
                        for offering in offerings
                        if offering.funding_type is funding_filter
                    )
                    years = tuple(
                        sorted(
                            {
                                int(offering.admission_year)
                                for offering in matching_offerings
                            }
                        )
                    )
                    if years:
                        matching_years[item.program_id] = years
                        for offering in matching_offerings:
                            for admission_source in offering.provenance:
                                source_url = str(admission_source.source_url)
                                funding_sources.setdefault(
                                    source_url,
                                    {
                                        "url": source_url,
                                        "source_name": admission_source.source_name
                                        or "Источник условий приёма",
                                        "kind": admission_source.source_kind,
                                        "locator": admission_source.locator,
                                        "captured_at": admission_source.captured_at.isoformat(),
                                    },
                                )
                supported = tuple(
                    item for item in supported if item.program_id in matching_years
                )
        rows: list[dict[str, object]] = []
        sources: dict[str, dict[str, object]] = dict(funding_sources)
        for item in supported:
            program = self._programs.get(item.program_id)
            direction = (
                self._universities.get_direction(program.direction_id)
                if program is not None and self._universities is not None
                else None
            )
            university = (
                self._universities.get(direction.university_id)
                if direction is not None and self._universities is not None
                else None
            )
            for reason in (*item.reasons, *item.anti_fit_reasons):
                for index, source in enumerate(reason.provenance):
                    source_url = str(source.url)
                    source_names = reason.source_names
                    sources.setdefault(
                        source_url,
                        {
                            "url": source_url,
                            "source_name": (
                                source_names[index]
                                if index < len(source_names)
                                else "Источник учебного плана"
                            ),
                            "kind": source.kind.value,
                            "locator": source.locator,
                            "captured_at": source.captured_at.isoformat(),
                        },
                    )
            rows.append(
                {
                    "program_id": item.program_id,
                    "program_code": item.program_code,
                    "program_name": item.program_name,
                    "matching_admission_years": matching_years.get(item.program_id, ()),
                    "university_id": direction.university_id if direction else None,
                    "university_name": university.name if university else None,
                    "content_fit": item.content_fit,
                    "reasons": tuple(reason.model_dump(mode="json") for reason in item.reasons),
                    "anti_fit_reasons": tuple(
                        reason.model_dump(mode="json")
                        for reason in item.anti_fit_reasons
                    ),
                    "evidence": item.evidence.model_dump(mode="json"),
                    "provenance": tuple(
                        source.model_dump(mode="json") for source in item.provenance
                    ),
                    "source_gaps": tuple(
                        gap.model_dump(mode="json") for gap in item.source_gaps
                    ),
                    "area_share": {
                        area.value: float(share)
                        for area, share in item.area_share.items()
                    },
                }
            )

        updated = session
        if rows:
            discovery = context.model_copy(
                update={
                    "candidate_program_ids": tuple(
                        row["program_id"] for row in rows
                    )
                }
            )
            updated = session.model_copy(
                update={
                    "program_discovery_context": discovery,
                    "last_result_ref": session.session_id,
                }
            )
        self._save(updated, base_revision)

        if rows:
            summary_lines = [
                f"Нашла {len(rows)} программ с учебными планами и источниками в доступном каталоге."
            ]
            if context.preferred_areas:
                liked = ", ".join(
                    area_definition(area).name for area in context.preferred_areas
                )
                summary_lines.append(f"Учла интерес: {liked}.")
            if context.avoided_areas:
                avoided = ", ".join(
                    area_definition(area).name for area in context.avoided_areas
                )
                summary_lines.append(f"Учла нежелательные области: {avoided}.")
            if funding_filter is not None:
                summary_lines.append(
                    "Оставила программы с опубликованными предложениями по условию "
                    f"«{_funding_label(funding_filter)}»; годы указаны у программ."
                )
            summary_lines.append(
                "Оценка Content Fit сравнивает содержание планов с вашими словами; "
                "это не прогноз поступления. Покрытие и источники показаны у каждой программы."
            )
            for index, row in enumerate(rows[:5], start=1):
                university_name = row["university_name"]
                label = f"{index}. {row['program_name']} ({row['program_code']})"
                if isinstance(university_name, str):
                    label += f" — {university_name}"
                if funding_filter is not None:
                    display_years = row["matching_admission_years"]
                    if isinstance(display_years, tuple):
                        label += "; годы предложения: " + ", ".join(
                            str(year) for year in display_years
                        )
                summary_lines.append(label)
            actions = (
                (
                    ResponseActionItem(
                        action=ResponseAction.COMPARE,
                        label="Сравнить первые две",
                        payload={
                            "programIds": ",".join(
                                str(row["program_id"]) for row in rows[:2]
                            )
                        },
                    ),
                )
                if len(rows) >= 2
                else ()
            )
            response = ResponseEnvelope(
                response_type=ResponseFormat.TEXT,
                template="program-recommendations",
                text="\n\n".join(summary_lines),
                data={
                    "recommendations": tuple(rows),
                    "sources": tuple(list(sources.values())[:20]),
                    "preferred_areas": tuple(
                        area.value for area in context.preferred_areas
                    ),
                    "avoided_areas": tuple(
                        area.value for area in context.avoided_areas
                    ),
                },
                actions=actions,
                metadata={
                    "coverage": "source_backed",
                    "candidate_count": len(rows),
                    "restricted_to_previous_candidates": referenced_candidates is not None,
                },
                result_reference=updated.session_id,
            )
        else:
            if funding_filter is not None:
                answer_text = (
                    "Для этого условия финансирования в доступных опубликованных "
                    "предложениях не нашла подтверждённых программ. Покрытие данных "
                    "ограничено; это не доказывает отсутствие таких мест."
                )
                status = "insufficient_admission_evidence"
            elif referenced_candidates is not None:
                answer_text = (
                    "Среди уже найденных программ не оказалось подтверждённого варианта "
                    "в выбранном вузе. Это не означает, что в вузе нет таких программ: "
                    "я проверила только предыдущую подборку. Напишите «поищи заново», "
                    "если нужно просмотреть весь доступный каталог этого вуза."
                )
                status = "no_match_in_previous_candidates"
            elif selected_fingerprints:
                answer_text = (
                    "В доступном каталоге есть программы, но их учебные планы или "
                    "происхождение данных не позволяют обоснованно ранжировать их по вашим критериям."
                )
                status = "insufficient_evidence"
            else:
                answer_text = (
                    "Не нашла подходящих программ с проверяемыми учебными планами "
                    "в текущем каталоге Andromeda. Покрытие каталога ограничено; "
                    "это не подтверждает отсутствие программ в вузе."
                )
                status = "outside_coverage"
            response = ResponseEnvelope(
                response_type=ResponseFormat.TEXT,
                template="program-recommendations",
                text=answer_text,
                data={"recommendations": (), "status": status},
                metadata={
                    "coverage": status,
                    "restricted_to_previous_candidates": referenced_candidates is not None,
                },
                result_reference=updated.session_id,
            )
        return AssistantResult(
            state=AssistantState.COMPLETE,
            session_id=updated.session_id,
            revision=updated.revision,
            response=response,
        )

    def _program_belongs_to_university(
        self, program_id: ProgramId, university_id: str
    ) -> bool:
        slug = university_id.removeprefix("university:")
        if str(program_id).startswith(f"program:{slug}:"):
            return True
        program = self._programs.get(program_id)
        if program is None or self._universities is None:
            return False
        direction = self._universities.get_direction(program.direction_id)
        return direction is not None and direction.university_id == university_id

    def _apply_comparison_defaults(self, session: QuerySession) -> QuerySession:
        if (
            session.intent is not ConversationIntent.COMPARE_PROGRAMS
            or session.metrics
            or ConversationSlot.ENTITY in session.missing_slots
        ):
            return session
        entity_count = sum(
            len(session.entities.get(entity_type, ()))
            for entity_type in (
                ResolutionEntityType.PROGRAM,
                ResolutionEntityType.DIRECTION,
            )
        )
        if entity_count < 2:
            return session
        preferred = ("programming_share", "ai_share", "math_share", "physics_share")
        metrics = tuple(code for code in preferred if code in self._allowed_metrics)
        if not metrics:
            return session
        missing_slots = tuple(
            slot for slot in session.missing_slots if slot is not ConversationSlot.METRIC
        )
        next_action = NextAction.EXECUTE_QUERY if not missing_slots else session.next_action
        return session.model_copy(
            update={
                "metrics": metrics,
                "missing_slots": missing_slots,
                "next_action": next_action,
                "last_action": next_action,
                "frame": session.frame.model_copy(
                    update={"metrics": metrics, "missing_fields": missing_slots}
                ),
            }
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
            rate_limit_key=session.owner_scope.owner_key,
            allow_naturalization=(
                query_context is not None
                and session.applicant_admission_context is None
                and query_context.focus
                in {
                    PolicyQueryFocus.STATUS,
                    PolicyQueryFocus.CHANGE,
                    PolicyQueryFocus.HISTORY,
                }
            ),
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

    def _handle_olympiad_benefits(
        self, session: QuerySession, base_revision: int | None
    ) -> AssistantResult:
        name = session.known_slots.get("olympiad_query")
        year = session.known_slots.get("admission_year")
        if not isinstance(name, str) or not isinstance(year, int):
            raise ContractError(
                ErrorCode.INVALID_QUERY, "olympiad inquiry needs a name and admission year"
            )
        def normalize(value: str) -> str:
            return " ".join(
                re.findall(r"[\w]+", value.casefold().replace("ё", "е"))
            )
        requested_name = normalize(name)
        matches: list[tuple[str, str, str, tuple[AdmissionBenefitRule, ...]]] = []
        if (
            self._admission_benefits is not None
            and self._universities is not None
            and requested_name not in {"олимпиада", "олимпиады", "диплом"}
        ):
            for university in self._universities.list():
                catalog = self._admission_benefits.get_catalog(university.id, year)
                if catalog is None:
                    continue
                for olympiad in catalog.olympiads:
                    official = normalize(olympiad.official_name)
                    if official == requested_name or (
                        len(requested_name) >= 6
                        and requested_name in official
                    ):
                        rules = tuple(
                            rule for rule in catalog.benefit_rules
                            if rule.olympiad_id == olympiad.id
                            and rule.status.value == "active"
                        )
                        matches.append(
                            (
                                str(university.name),
                                str(olympiad.official_name),
                                catalog.coverage.status.value,
                                rules,
                            )
                        )
        lines: list[str]
        details: dict[str, object] = {"admission_year": year}
        if not matches:
            lines = [
                (f"Для олимпиады «{name}» на {year} год не удалось подтвердить "
                 "правила по доступным source-backed каталогам."),
                ("Это пробел покрытия, а не утверждение об отсутствии права. "
                 "Уточните официальное название, профиль и год диплома."),
            ]
            mode = ResponseMode.UNVERIFIED_FALLBACK
        else:
            distinct_names = {normalize(name) for _, name, _, _ in matches}
            if len(distinct_names) > 1:
                options = tuple(
                    dict.fromkeys(name for _, name, _, _ in matches)
                )[:12]
                question = "Найдено несколько олимпиад. Уточните официальное название."
                session = session.model_copy(update={"last_question": question})
                self._save(session, base_revision)
                return AssistantResult(
                    state=AssistantState.NEEDS_CLARIFICATION,
                    session_id=session.session_id,
                    revision=session.revision,
                    question=question,
                    options=options,
                    missing_slots=(ConversationSlot.OLYMPIAD,),
                )
            lines = [
                f"Олимпиада: {matches[0][1]}. Год приёма: {year}.",
                ("Ниже опубликованные условия; личное право на льготу здесь "
                 "не рассчитано без программы, результата и проверки условий."),
            ]
            listed_rules = 0
            for university_name, _, coverage, rules in matches:
                lines.append(
                    f"{university_name}: покрытие {coverage}, "
                    f"опубликованных правил {len(rules)}."
                )
                for rule in rules[:6]:
                    condition = (
                        rule.result_type.value if rule.result_type is not None
                        else "тип диплома не указан"
                    )
                    lines.append(
                        f"• {rule.benefit_type.value}; результат: {condition}; "
                        f"источник: {rule.provenance.source.url}"
                    )
                    listed_rules += 1
                if len(rules) > 6:
                    lines.append(f"Показаны 6 из {len(rules)} правил этого вуза.")
            if listed_rules == 0:
                lines.append(
                    "Применимое правило в доступном каталоге не подтверждено; "
                    "это не доказательство отсутствия льготы."
                )
            details["matched_rule_count"] = listed_rules
            mode = ResponseMode.DETERMINISTIC
        self._save(session, base_revision)
        return AssistantResult(
            state=AssistantState.COMPLETE,
            session_id=session.session_id,
            revision=session.revision,
            response=ResponseEnvelope(
                response_type=ResponseFormat.TEXT,
                response_mode=mode,
                template="olympiad-benefits",
                text="\n".join(lines),
                data=details,
                result_reference=session.session_id,
            ),
        )

    def _handle_program_details(
        self, session: QuerySession, base_revision: int | None
    ) -> AssistantResult:
        program_ids = tuple(session.entities.get(ResolutionEntityType.PROGRAM, ()))
        if len(program_ids) != 1:
            raise ContractError(
                ErrorCode.INVALID_QUERY, "program details require one resolved program"
            )
        program = self._programs.get(program_ids[0])
        if program is None:
            raise NotFoundError("Program was not found in the available catalog")
        curriculum = (
            self._curricula.get_for_program(program.id)
            if self._curricula is not None
            else None
        )
        lines = [
            f"{program.name} ({program.code}).",
            f"Год программы: {program.education_year}.",
            f"Источник программы: {program.source_url}",
        ]
        details: dict[str, object] = {
            "program_id": program.id,
            "program_name": program.name,
            "program_code": program.code,
            "education_year": program.education_year,
            "source_url": str(program.source_url),
        }
        if program.source_gaps:
            lines.append(
                f"В карточке отмечено пробелов в источнике: {len(program.source_gaps)}."
            )
        if curriculum is None:
            lines.append("Учебный план этой программы в доступных данных не подтверждён.")
        else:
            semester = session.frame.semester
            course_year = session.frame.course_year
            items = tuple(
                item
                for item in curriculum.items
                if (semester is None or item.semester == semester)
                and (
                    course_year is None
                    or (
                        item.semester is not None
                        and (item.semester + 1) // 2 == course_year
                    )
                )
            )
            filter_label = (
                f"семестр {semester}" if semester is not None
                else f"курс {course_year}" if course_year is not None
                else "весь план"
            )
            lines.append(
                f"Учебный план ({filter_label}, год {curriculum.education_year}): "
                f"{len(items)} записей из {len(curriculum.items)}."
            )
            if not items:
                lines.append(
                    "Для выбранного периода дисциплины не подтверждены доступным планом."
                )
            for item in items[:24]:
                workload = f"{item.hours} ч."
                if item.credits is not None:
                    workload += f", {item.credits} ЗЕТ"
                when = (
                    f", семестр {item.semester}"
                    if item.semester is not None
                    else ", семестр не указан"
                )
                lines.append(f"• {item.source_name} — {workload}{when}")
            if len(items) > 24:
                lines.append(
                    f"Показаны первые 24 записи; ещё {len(items) - 24} "
                    "доступны в исходном учебном плане."
                )
            lines.append(f"Источник учебного плана: {curriculum.source_url}")
            if curriculum.source_gaps:
                lines.append(
                    f"В плане отмечено пробелов в источнике: {len(curriculum.source_gaps)}."
                )
            details["curriculum"] = {
                "education_year": curriculum.education_year,
                "source_url": str(curriculum.source_url),
                "total_items": len(curriculum.items),
                "selected_items": len(items),
                "semester": semester,
                "course_year": course_year,
            }
        session = session.model_copy(update={"last_result_ref": str(program.id)})
        self._save(session, base_revision)
        return AssistantResult(
            state=AssistantState.COMPLETE,
            session_id=session.session_id,
            revision=session.revision,
            response=ResponseEnvelope(
                response_type=ResponseFormat.TEXT,
                template="program-details",
                text="\n".join(lines),
                data=details,
                result_reference=str(program.id),
            ),
        )

    def _naturalize_ordinary_result(
        self,
        result: AssistantResult,
        *,
        rate_limit_key: str,
    ) -> AssistantResult:
        response = result.response
        if (
            result.state is not AssistantState.COMPLETE
            or response is None
            or response.knowledge is not None
            or response.response_mode is not ResponseMode.DETERMINISTIC
        ):
            return result
        rendered = self._knowledge_response_renderer.naturalize_text(
            response.text,
            rate_limit_key=rate_limit_key,
        )
        if rendered.response_mode is ResponseMode.DETERMINISTIC:
            return result
        return result.model_copy(
            update={
                "response": response.model_copy(
                    update={
                        "text": rendered.text,
                        "response_mode": rendered.response_mode,
                    }
                )
            }
        )

    def _clarify_with_ai(
        self,
        current_question: str,
        session: QuerySession,
        user_message: str,
        options: tuple[str, ...],
        *,
        rate_limit_key: str,
    ) -> str:
        if self._conversation_ai is None:
            return current_question
        request = AssistantClarificationRequest(
            user_message=user_message[:2_000],
            intent=session.intent,
            missing_slots=session.missing_slots,
            available_options=options[:20],
            current_question=current_question,
            resolved_entities=tuple(
                entity_id
                for values in session.entities.values()
                for entity_id in values
            )[:16],
            unresolved_entities=session.unresolved_entities[:16],
        )
        try:
            candidate = self._conversation_ai.clarify(
                request, rate_limit_key=rate_limit_key
            )
            if clarification_is_grounded(candidate, request):
                return candidate
            logger.info("assistant_clarification_fallback reason=ungrounded")
        except Exception as error:  # noqa: BLE001 - deterministic clarification remains available.
            logger.warning(
                "assistant_clarification_fallback error_type=%s",
                type(error).__name__,
            )
        return current_question

    def _select_other_direction(
        self,
        session: QuerySession,
        user_message: str,
        *,
        rate_limit_key: str,
    ) -> tuple[QuerySession, bool, tuple[str, ...]]:
        """Let AI choose only among real programs in the selected university."""

        current_direction_ids = tuple(
            session.entities.get(ResolutionEntityType.DIRECTION, ())
        )
        current_program_ids = tuple(
            session.entities.get(ResolutionEntityType.PROGRAM, ())
        )
        selected_programs = tuple(
            program
            for program_id in current_program_ids
            if (program := self._programs.get(program_id)) is not None
        )
        current_directions = set(current_direction_ids)
        current_directions.update(program.direction_id for program in selected_programs)

        if current_direction_ids:
            selected_type = ResolutionEntityType.DIRECTION
            reference_direction = current_direction_ids[0]
        elif selected_programs:
            selected_type = ResolutionEntityType.PROGRAM
            reference_direction = selected_programs[0].direction_id
        else:
            # Without a resolved baseline, ask for a real catalog item instead
            # of fabricating one from the user's phrase.
            return session, False, ()

        direction_parts = reference_direction.split(":")
        if len(direction_parts) != 3 or direction_parts[0] != "direction":
            return session, False, ()
        university_id = f"university:{direction_parts[1]}"
        catalog_programs = self._programs.list(university_id=university_id)
        candidates: list[AssistantEntityCandidate] = []
        seen_directions: set[str] = set()
        for program in sorted(
            catalog_programs,
            key=lambda item: (
                item.direction_id,
                str(item.name).casefold(),
                str(item.code),
            ),
        ):
            if program.direction_id in current_directions:
                continue
            if selected_type is ResolutionEntityType.DIRECTION:
                if program.direction_id in seen_directions:
                    continue
                seen_directions.add(program.direction_id)
                label = (
                    f"{program.direction_id.rsplit(':', 1)[-1]} — "
                    f"{program.name} ({program.code})"
                )
                canonical_id = program.direction_id
            else:
                label = (
                    f"{program.direction_id.rsplit(':', 1)[-1]} — "
                    f"{program.name} ({program.code})"
                )
                canonical_id = program.id
            candidates.append(
                AssistantEntityCandidate(
                    entity_type=selected_type,
                    canonical_id=canonical_id,
                    label=label,
                )
            )
        candidates.sort(key=lambda item: (item.label.casefold(), item.canonical_id))
        candidates = candidates[:40]
        if not candidates:
            return session, True, ()

        options = tuple(item.label for item in candidates[:4])
        if self._conversation_ai is None:
            return session, False, options
        try:
            selected_id = self._conversation_ai.select_catalog_candidate(
                user_message,
                candidates=tuple(candidates),
                rate_limit_key=rate_limit_key,
            )
        except Exception as error:  # noqa: BLE001 - offer actual choices on provider failure.
            logger.warning(
                "assistant_catalog_selection_fallback error_type=%s",
                type(error).__name__,
            )
            return session, False, options
        selected = next(
            (item for item in candidates if item.canonical_id == selected_id),
            None,
        )
        if selected is None:
            return session, False, options
        candidate_hash = hashlib.sha256(
            "\n".join(item.canonical_id for item in candidates).encode("utf-8")
        ).hexdigest()
        updated = add_bounded_catalog_selection(
            session,
            entity_type=selected.entity_type,
            canonical_id=selected.canonical_id,
            candidate_hash=candidate_hash,
        )
        logger.info(
            "assistant_catalog_selection source=polza entity_type=%s candidate_count=%d",
            selected.entity_type.value,
            len(candidates),
        )
        return updated, False, ()

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
        if (
            session.intent is ConversationIntent.COMPARE_PROGRAMS
            and len(resolved.get(ResolutionEntityType.PROGRAM, ())) >= 2
        ):
            # Two exact program IDs fully define a comparison even if a spoken
            # university alias could not be resolved independently.
            unresolved = [
                item for item in unresolved if not item.startswith("university:")
            ]
            resolved.pop(ResolutionEntityType.UNIVERSITY, None)
        if not unresolved:
            missing_slots = session.missing_slots
            next_action = session.next_action
            if (
                session.intent is ConversationIntent.COMPARE_PROGRAMS
                and (
                    len(resolved.get(ResolutionEntityType.PROGRAM, ()))
                    + len(resolved.get(ResolutionEntityType.DIRECTION, ()))
                    >= 2
                )
            ):
                missing_slots = tuple(
                    slot
                    for slot in missing_slots
                    if slot
                    not in {
                        ConversationSlot.ENTITY,
                        ConversationSlot.UNIVERSITY_SCOPE,
                    }
                )
                if not session.metrics and ConversationSlot.METRIC not in missing_slots:
                    missing_slots = (*missing_slots, ConversationSlot.METRIC)
                next_action = (
                    NextAction.ASK_FOR_METRIC
                    if ConversationSlot.METRIC in missing_slots
                    else NextAction.EXECUTE_QUERY
                    if not missing_slots
                    else session.next_action
                )
            return session.model_copy(
                update={
                    "entities": resolved,
                    "resolution_cache": resolution_cache,
                    "unresolved_entities": (),
                    "missing_slots": missing_slots,
                    "next_action": next_action,
                    "last_action": next_action,
                    "frame": session.frame.model_copy(
                        update={
                            "entities": resolved,
                            "missing_fields": missing_slots,
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

    def _prepare_comparison_follow_up(
        self,
        session: QuerySession,
        text: str,
        parsed: ParsedQuery,
    ) -> tuple[ParsedQuery, str | None]:
        if parsed.intent in {
            ConversationIntent.ADMISSION_SEARCH,
            ConversationIntent.KNOWLEDGE_POLICY_QUERY,
        }:
            return parsed, None
        parsed = parsed.model_copy(
            update={
                "intent": ConversationIntent.COMPARE_PROGRAMS,
                "metric_codes": tuple(
                    dict.fromkeys((*session.metrics, *parsed.metric_codes))
                ),
            }
        )
        if session.next_action is NextAction.ASK_FOR_METRIC:
            return parsed, None
        if any(
            query.startswith(("program:", "direction:"))
            for query in (*parsed.program_queries, *parsed.direction_queries)
        ):
            return parsed, None
        if self._entity_resolver is None:
            return parsed.model_copy(update={"program_queries": (text.strip(),)}), None

        allowed_types = _comparison_entity_types(session)
        context = _comparison_resolution_context(session)
        full_matches = tuple(
            entity_type
            for entity_type in allowed_types
            if self._comparison_entity_match(entity_type, text.strip(), context=context)
        )
        if len(full_matches) == 1:
            return (
                _with_comparison_entity_queries(
                    parsed,
                    full_matches[0],
                    (text.strip(),),
                    source_text=text,
                ),
                None,
            )
        if len(full_matches) > 1:
            return parsed, (
                "Это название подходит и программе, и направлению. "
                "Уточните вуз и напишите, что именно сравниваем."
            )

        typed_parser_matches = tuple(
            (entity_type, query)
            for entity_type, queries in (
                (ResolutionEntityType.PROGRAM, parsed.program_queries),
                (ResolutionEntityType.DIRECTION, parsed.direction_queries),
            )
            if entity_type in allowed_types
            for query in queries
            if self._comparison_entity_match(entity_type, query, context=context)
        )
        if typed_parser_matches:
            matched_types = {entity_type for entity_type, _ in typed_parser_matches}
            if len(matched_types) == 1:
                entity_type = typed_parser_matches[0][0]
                typed_queries = tuple(
                    query
                    for candidate_type, query in typed_parser_matches
                    if candidate_type is entity_type
                )
                return (
                    _with_comparison_entity_queries(
                        parsed,
                        entity_type,
                        typed_queries,
                        source_text=text,
                    ),
                    None,
                )
            return parsed, (
                "Это название подходит и программе, и направлению. "
                "Уточните вуз и напишите, что именно сравниваем."
            )

        pair_matches: dict[
            tuple[ResolutionEntityType, str, str], tuple[str, str]
        ] = {}
        partial_matches: dict[
            tuple[ResolutionEntityType, str, str], tuple[str, str]
        ] = {}
        separators = tuple(
            re.finditer(
                r"\s+(?:и|,|;|/|vs\.?|versus)\s+",
                text.strip(),
                re.IGNORECASE,
            )
        )[:8]
        normalized_text = text.strip()
        for separator in separators:
            left = normalized_text[: separator.start()].strip()
            right = normalized_text[separator.end() :].strip()
            if not left or not right or len(left) > 512 or len(right) > 512:
                continue
            for entity_type in allowed_types:
                left_match = self._comparison_entity_match(
                    entity_type, left, context=context
                )
                right_match = self._comparison_entity_match(
                    entity_type, right, context=context
                )
                if left_match and right_match and left_match != right_match:
                    pair_matches[(entity_type, left_match, right_match)] = (
                        left,
                        right,
                    )
                elif left_match or right_match:
                    matched_id = left_match or right_match
                    unresolved_query = right if left_match else left
                    assert matched_id is not None
                    partial_matches[
                        (entity_type, matched_id, unresolved_query.casefold())
                    ] = (left, right)

        if len(pair_matches) == 1:
            (entity_type, _, _), queries = next(iter(pair_matches.items()))
            return (
                _with_comparison_entity_queries(
                    parsed, entity_type, queries, source_text=text
                ),
                None,
            )
        if len(pair_matches) > 1:
            return parsed, (
                "Не смогла однозначно разделить названия. "
                "Напишите каждое направление или программу отдельным сообщением."
            )
        if len(partial_matches) == 1:
            (entity_type, _, _), queries = next(iter(partial_matches.items()))
            return (
                _with_comparison_entity_queries(
                    parsed, entity_type, queries, source_text=text
                ),
                None,
            )
        if len(partial_matches) > 1:
            return parsed, (
                "Не смогла однозначно сопоставить названия. "
                "Напишите одно направление или программу за раз, вместе с вузом."
            )

        logger.debug(
            "[FIX] comparison_entity_resolution unresolved input_length=%d candidate_types=%d",
            len(normalized_text),
            len(allowed_types),
        )
        return _with_comparison_entity_queries(
            parsed,
            allowed_types[0],
            (normalized_text[:512],),
        ), None

    def _comparison_entity_match(
        self,
        entity_type: ResolutionEntityType,
        query: str,
        *,
        context: ResolutionContext | None,
    ) -> str | None:
        if self._entity_resolver is None or not query:
            return None
        result = self._entity_resolver.resolve(
            entity_type, query, context=context, limit=10
        )
        if (
            result.resolution_strategy == "deterministic"
            and result.status in {ResolutionStatus.EXACT, ResolutionStatus.RESOLVED}
        ):
            return result.selected_id
        return None

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
        if base_revision is not None and session.revision == base_revision:
            # A clarification that adds no typed information should repeat the
            # current question without attempting a non-advancing repository write.
            return
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


def _restart_session(
    session: QuerySession, *, clear_task_facts: bool = False
) -> QuerySession:
    """Start another task with the same conversation identity."""

    return QuerySession(
        session_id=session.session_id,
        owner_scope=session.owner_scope,
        known_slots={} if clear_task_facts else session.known_slots,
        confirmed_parameters={} if clear_task_facts else session.confirmed_parameters,
        inferred_parameters={} if clear_task_facts else session.inferred_parameters,
        applicant_admission_context=session.applicant_admission_context,
        program_discovery_context=session.program_discovery_context,
        assumptions=() if clear_task_facts else session.assumptions,
        last_result_ref=None if clear_task_facts else session.last_result_ref,
        revision=session.revision,
        parser_version=session.parser_version,
        policy_version=session.policy_version,
        created_at=session.created_at,
        updated_at=session.updated_at,
        expires_at=session.expires_at,
    )


def _apply_contextual_follow_up(
    parsed: ParsedQuery, existing: QuerySession | None, text: str
) -> ParsedQuery:
    if existing is None:
        return parsed
    normalized = " ".join(text.casefold().replace("ё", "е").split())
    if (
        existing.intent is ConversationIntent.PROGRAM_DISCOVERY
        and existing.program_discovery_context is not None
        and parsed.intent is ConversationIntent.ADMISSION_SEARCH
        and parsed.funding_type is not None
        and parsed.total_score is None
        and not parsed.exam_scores
        and parsed.admission_year is None
        and not re.search(r"\b(?:поступ\w*|шанс\w*|балл\w*|егэ)\b", normalized)
    ):
        parsed = parsed.model_copy(
            update={"intent": ConversationIntent.PROGRAM_DISCOVERY, "starts_new_task": False}
        )
    if (
        ConversationSlot.ADMISSION_YEAR in existing.missing_slots
        and parsed.admission_year is None
    ):
        year_reply = re.fullmatch(
            r"(?:поступ\w*\s+)?(?:в|на)?\s*(20\d{2})"
            r"(?:\s*(?:году|год|г\.?))?[.!]?",
            normalized,
        )
        if year_reply is not None:
            parsed = parsed.model_copy(
                update={"admission_year": int(year_reply.group(1))}
            )
    if (
        existing.intent is ConversationIntent.KNOWLEDGE_POLICY_QUERY
        and ConversationSlot.ADMISSION_YEAR in existing.missing_slots
        and parsed.admission_year is not None
        and parsed.policy_query_context is None
        and not parsed.starts_new_task
    ):
        parsed = parsed.model_copy(
            update={
                "intent": ConversationIntent.KNOWLEDGE_POLICY_QUERY,
                "policy_query_context": existing.policy_query_context,
            }
        )
    if (
        existing.intent is ConversationIntent.OLYMPIAD_BENEFITS
        and not parsed.starts_new_task
        and parsed.intent in {ConversationIntent.UNKNOWN, ConversationIntent.ADMISSION_SEARCH}
        and parsed.total_score is None
        and not parsed.exam_scores
        and parsed.funding_type is None
        and parsed.study_form is None
    ):
        update: dict[str, object] = {"intent": ConversationIntent.OLYMPIAD_BENEFITS}
        if (
            ConversationSlot.OLYMPIAD in existing.missing_slots
            and parsed.olympiad_query is None
            and parsed.admission_year is None
            and "?" not in text
            and 1 <= len(text.strip()) <= 256
        ):
            update["olympiad_query"] = text.strip()
        parsed = parsed.model_copy(update=update)
    if (
        parsed.intent
        in {ConversationIntent.PROGRAM_DETAILS, ConversationIntent.ANALYTICS_QUERY}
        and not parsed.program_queries
        and not parsed.direction_queries
        and not parsed.university_queries
        and (
            existing.intent
            in {ConversationIntent.PROGRAM_DETAILS, ConversationIntent.ANALYTICS_QUERY}
            or (
                parsed.intent is ConversationIntent.PROGRAM_DETAILS
                and re.search(r"\b(?:эт\w*|выбранн\w*|ней|нее|её|ее)\b", normalized)
            )
        )
        and not parsed.starts_new_task
    ):
        program_ids = tuple(existing.entities.get(ResolutionEntityType.PROGRAM, ()))
        if not program_ids and existing.program_discovery_context is not None:
            program_ids = existing.program_discovery_context.candidate_program_ids
        if len(program_ids) == 1:
            parsed = parsed.model_copy(update={"program_queries": program_ids})
    if parsed.starts_new_task:
        return parsed
    policy_context = existing.policy_query_context
    if (
        policy_context is not None
        and parsed.policy_query_context is None
        and _is_policy_context_follow_up(normalized)
        and not _starts_independent_task(parsed, normalized)
    ):
        history_follow_up = any(
            marker in normalized
            for marker in (
                "как это правило работало",
                "как правило работало",
                "что действовало",
                "чем отличал",
                "как было",
                "в прошлом году",
                "исторически",
            )
        ) or bool(re.search(r"\b20\d{2}\b", normalized)) and any(
            marker in normalized
            for marker in ("правил", "норм", "действ", "работал", "ввод", "вступ")
        )
        focus = (
            PolicyQueryFocus.HISTORY
            if history_follow_up
            else PolicyQueryFocus.STATUS
        )
        year_match = re.search(r"\b(19|20|21)\d{2}\b", normalized)
        context_updates: dict[str, object] = {"focus": focus}
        if history_follow_up and year_match is not None:
            context_updates["mentioned_effective_year"] = PolicyQueryYear(
                year=int(year_match.group(0))
            )
        return parsed.model_copy(
            update={
                "intent": ConversationIntent.KNOWLEDGE_POLICY_QUERY,
                "policy_query_context": policy_context.model_copy(
                    update=context_updates
                ),
                # A year in a rule-history follow-up is not the applicant's year.
                "admission_year": None,
            }
        )
    if (
        existing.intent is ConversationIntent.COMPARE_PROGRAMS
        and ConversationSlot.ENTITY in existing.missing_slots
        and parsed.intent
        in {
            ConversationIntent.UNKNOWN,
            ConversationIntent.ANALYTICS_QUERY,
            ConversationIntent.COMPARE_PROGRAMS,
        }
        and parsed.total_score is None
        and not parsed.exam_scores
        and parsed.funding_type is None
        and parsed.study_form is None
        and parsed.admission_year is None
        and len(normalized) >= 8
        and not normalized.startswith(
            ("почему", "зачем", "сколько", "где больше", "где меньше", "что значит")
        )
    ):
        # The user is answering the bot's open comparison prompt. Keep that
        # task active even when a program name contains a word such as "ИИ"
        # that the standalone parser also recognizes as an analytics metric.
        parsed = parsed.model_copy(update={"intent": ConversationIntent.COMPARE_PROGRAMS})
    if (
        existing.intent is ConversationIntent.PROGRAM_DISCOVERY
        and ConversationSlot.INTERESTS in existing.missing_slots
        and parsed.intent
        in {
            ConversationIntent.UNKNOWN,
            ConversationIntent.ANALYTICS_QUERY,
            ConversationIntent.PROGRAM_DISCOVERY,
        }
        and parsed.total_score is None
        and not parsed.exam_scores
        and parsed.funding_type is None
        and parsed.study_form is None
        and parsed.admission_year is None
    ):
        preferred_areas, avoided_areas = extract_explicit_area_preferences(
            normalized, infer_from_area_mention=True
        )
        if preferred_areas or avoided_areas:
            # The active question asked for interests, so a short answer such
            # as "AI" is a preference here, not a standalone analytics query.
            parsed = parsed.model_copy(
                update={
                    "intent": ConversationIntent.PROGRAM_DISCOVERY,
                    "preferred_areas": preferred_areas,
                    "avoided_areas": avoided_areas,
                    "metric_codes": (),
                }
            )
    if (
        existing.intent is ConversationIntent.ADMISSION_SEARCH
        and not existing.missing_slots
        and parsed.policy_query_context is None
        and parsed.total_score is None
        and not parsed.exam_scores
    ):
        score_match = re.fullmatch(
            r"(?:а\s+)?если\s+(?:(?:у\s+меня)\s+)?(?:будет\s+)?(\d{3})\s*(?:балл(?:а|ов)?)?[?.!]*",
            normalized,
        )
        if score_match is not None and 100 < int(score_match.group(1)) <= 400:
            parsed = parsed.model_copy(
                update={
                    "intent": ConversationIntent.ADMISSION_SEARCH,
                    "total_score": Decimal(score_match.group(1)),
                }
            )
    if existing.missing_slots:
        return parsed
    candidate_reference = _is_discovery_candidate_reference(normalized)
    discovery = existing.program_discovery_context
    has_applicant_inputs = any(
        (
            parsed.total_score is not None,
            bool(parsed.exam_scores),
            parsed.funding_type is not None,
            parsed.study_form is not None,
            parsed.admission_year is not None,
        )
    )
    has_admission_language = any(
        marker in normalized
        for marker in (
            "поступ", "егэ", "балл", "шанс", "проходн", "бюджет", "платн",
        )
    )
    discovery_scope_follow_up = (
        discovery is not None
        and not has_applicant_inputs
        and not has_admission_language
        and (candidate_reference or bool(parsed.university_queries))
    )
    if (
        discovery is not None
        and (
            (candidate_reference and bool(discovery.candidate_program_ids))
            or (
                bool(parsed.university_queries)
                and existing.intent is ConversationIntent.PROGRAM_DISCOVERY
            )
        )
        and parsed.policy_query_context is None
        and parsed.intent
        in {
            ConversationIntent.UNKNOWN,
            ConversationIntent.ANALYTICS_QUERY,
            ConversationIntent.COMPARE_PROGRAMS,
            ConversationIntent.PROGRAM_DISCOVERY,
        }
        | ({ConversationIntent.ADMISSION_SEARCH} if discovery_scope_follow_up else set())
    ):
        program_queries = parsed.program_queries
        if candidate_reference:
            candidate_ids = discovery.candidate_program_ids
            if "первые две" in normalized or "первые два" in normalized:
                candidate_ids = candidate_ids[:2]
            program_queries = tuple(
                dict.fromkeys((*program_queries, *candidate_ids))
            )
        next_intent = (
            ConversationIntent.COMPARE_PROGRAMS
            if candidate_reference
            and parsed.intent is ConversationIntent.COMPARE_PROGRAMS
            else ConversationIntent.PROGRAM_DISCOVERY
        )
        return parsed.model_copy(
            update={
                "intent": next_intent,
                "program_queries": program_queries,
            }
        )

    metric_only_comparison_follow_up = (
        bool(parsed.metric_codes)
        and not parsed.university_queries
        and not parsed.direction_queries
        and not parsed.program_queries
        and not parsed.total_score
        and not parsed.exam_scores
    )
    if (
        existing.intent is ConversationIntent.COMPARE_PROGRAMS
        and (
            _is_comparison_reference(normalized)
            or metric_only_comparison_follow_up
        )
        and parsed.policy_query_context is None
        and parsed.intent
        in {
            ConversationIntent.UNKNOWN,
            ConversationIntent.ANALYTICS_QUERY,
            ConversationIntent.COMPARE_PROGRAMS,
        }
        | (
            {ConversationIntent.PROGRAM_DISCOVERY}
            if _is_comparison_reference(normalized)
            else set()
        )
    ):
        prior_programs = existing.entities.get(ResolutionEntityType.PROGRAM, ())
        prior_directions = existing.entities.get(ResolutionEntityType.DIRECTION, ())
        if prior_programs or prior_directions:
            return parsed.model_copy(
                update={
                    "intent": ConversationIntent.COMPARE_PROGRAMS,
                    "program_queries": tuple(
                        dict.fromkeys((*parsed.program_queries, *prior_programs))
                    ),
                    "direction_queries": tuple(
                        dict.fromkeys((*parsed.direction_queries, *prior_directions))
                    ),
                    "replace_metrics": bool(parsed.metric_codes),
                }
            )
    return parsed


def _is_policy_context_follow_up(text: str) -> bool:
    has_reference = bool(re.search(r"\b(?:он|она|оно|его|её|ее)\b", text)) or any(
        marker in text
        for marker in (
            "это",
            "этот",
            "эта",
            "этого",
            "этому",
            "такое правило",
            "это правило",
            "по этому правилу",
        )
    )
    has_policy_question = any(
        marker in text
        for marker in (
            "с какого",
            "с какого числа",
            "с какого года",
            "действует",
            "вступил",
            "вступает",
            "принято",
            "работало",
            "действовало",
            "исторически",
            "что измен",
            "чем отличал",
        )
    )
    return has_reference and has_policy_question


def _starts_independent_task(parsed: ParsedQuery, text: str) -> bool:
    if (
        parsed.total_score is not None
        or parsed.exam_scores
        or parsed.metric_codes
        or parsed.funding_type is not None
        or parsed.study_form is not None
    ):
        return True
    return any(
        marker in text
        for marker in (
            "подбери программу",
            "найди программу",
            "покажи программы",
            "сравни",
            "куда поступ",
            "на что поступ",
            "программирование",
        )
    )


def _is_discovery_candidate_reference(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "из этого",
            "из этих",
            "из них",
            "среди этих",
            "среди них",
            "из уже найден",
            "из подборки",
            "первые две",
            "первые два",
        )
    )


def _is_admission_guarantee_question(text: str) -> bool:
    normalized = " ".join(text.casefold().replace("ё", "е").split())
    if not any(marker in normalized for marker in ("точно", "гарант", "обязательно")):
        return False
    return any(marker in normalized for marker in ("поступ", "зачисл", "возьмут"))


def _is_comparison_reference(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "их",
            "эти программы",
            "эти направления",
            "первые две",
            "первые два",
            "обе",
            "между ними",
            "из них",
            "где больше",
            "где меньше",
            "а где",
            "какая из них",
            "какой из них",
            "какие из них",
            "а теперь только",
            "только по",
            "по ним",
        )
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


def _without_unresolved_comparison_inputs(session: QuerySession) -> QuerySession:
    unresolved_by_type: dict[ResolutionEntityType, set[str]] = {}
    for unresolved in session.unresolved_entities:
        entity_type, separator, query = unresolved.partition(":")
        if not separator:
            continue
        try:
            typed_entity = ResolutionEntityType(entity_type)
        except ValueError:
            continue
        unresolved_by_type.setdefault(typed_entity, set()).add(query)
    if not unresolved_by_type:
        return session
    entities = {key: tuple(values) for key, values in session.entities.items()}
    for entity_type, unresolved_queries in unresolved_by_type.items():
        remaining = tuple(
            value
            for value in entities.get(entity_type, ())
            if value not in unresolved_queries
        )
        if remaining:
            entities[entity_type] = remaining
        else:
            entities.pop(entity_type, None)
    return session.model_copy(
        update={
            "entities": entities,
            "unresolved_entities": (),
            "frame": session.frame.model_copy(update={"entities": entities}),
        }
    )


def _comparison_entity_types(
    session: QuerySession,
) -> tuple[ResolutionEntityType, ...]:
    comparison_types = (
        ResolutionEntityType.PROGRAM,
        ResolutionEntityType.DIRECTION,
    )
    existing_types = tuple(
        entity_type
        for entity_type in comparison_types
        if session.entities.get(entity_type)
    )
    return existing_types if len(existing_types) == 1 else comparison_types


def _comparison_resolution_context(
    session: QuerySession,
) -> ResolutionContext | None:
    university_ids = tuple(
        session.entities.get(ResolutionEntityType.UNIVERSITY, ())
    )
    if len(university_ids) != 1 or not university_ids[0].startswith("university:"):
        return None
    return ResolutionContext(university_id=university_ids[0])


def _with_comparison_entity_queries(
    parsed: ParsedQuery,
    entity_type: ResolutionEntityType,
    queries: tuple[str, ...],
    *,
    source_text: str | None = None,
) -> ParsedQuery:
    update: dict[str, object] = {
        "program_queries": (
            queries
            if entity_type is ResolutionEntityType.PROGRAM
            else parsed.program_queries
        ),
        "direction_queries": (
            queries
            if entity_type is ResolutionEntityType.DIRECTION
            else parsed.direction_queries
        ),
    }
    if source_text is not None:
        update["metric_codes"] = remove_entity_name_metrics(
            source_text, parsed.metric_codes, queries
        )
    return parsed.model_copy(update=update)


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
