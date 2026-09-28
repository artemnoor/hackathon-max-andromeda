from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from andromeda.infrastructure.adapters.policy_approval_conflicts import (
    SqlAlchemyPolicyApprovalConflictReader,
)
from andromeda.infrastructure.adapters.polza_naturalizer import PolzaNaturalizer
from andromeda.infrastructure.config.settings import Settings
from andromeda.infrastructure.jev.runtime import (
    build_admission_candidate_selector,
    build_decision_policy,
)
from andromeda.infrastructure.jev_tree.adapter import JevTreeAdapter
from andromeda.infrastructure.jev_tree.config import JevTreeConfig
from andromeda.infrastructure.jev_tree.transport import NodeJevTreeTransport
from andromeda.infrastructure.jevql.adapter import JevQLAdapter
from andromeda.infrastructure.jevql.config import JevQLConfig, JevQLMode
from andromeda.infrastructure.repositories.admin_ops import SqlAlchemyIngestionRunReader
from andromeda.infrastructure.repositories.admission_benefit_policy import (
    AdmissionBenefitsPolicyRuleReader,
)
from andromeda.infrastructure.repositories.admission_benefits import (
    SqlAlchemyAdmissionBenefitsRepository,
)
from andromeda.infrastructure.repositories.admission_cycles import (
    SqlAlchemyAdmissionCycleRepository,
)
from andromeda.infrastructure.repositories.admission_fit import (
    SqlAlchemyAdmissionFitReader,
)
from andromeda.infrastructure.repositories.admission_policy import (
    AdmissionsPolicyRuleReader,
)
from andromeda.infrastructure.repositories.admissions import (
    SqlAlchemyAdmissionRepository,
)
from andromeda.infrastructure.repositories.analytics import (
    SqlAlchemyProgramProjectionRepository,
)
from andromeda.infrastructure.repositories.auth import SqlAlchemyAccountRepository
from andromeda.infrastructure.repositories.campus import SqlAlchemyCampusPointRepository
from andromeda.infrastructure.repositories.curricula import (
    SqlAlchemyCurriculumRepository,
)
from andromeda.infrastructure.repositories.decision import (
    SqlAlchemyDecisionContextRepository,
)
from andromeda.infrastructure.repositories.decision_analytics import (
    SqlAlchemyDecisionAnalyticsRepository,
)
from andromeda.infrastructure.repositories.decision_candidates import (
    CatalogDecisionCandidateSource,
)
from andromeda.infrastructure.repositories.derived_refresh import (
    SqlAlchemyDerivedRefreshAdapter,
)
from andromeda.infrastructure.repositories.disciplines import (
    SqlAlchemyDisciplineRepository,
)
from andromeda.infrastructure.repositories.entity_resolution import (
    SqlAlchemyEntityResolutionRepository,
)
from andromeda.infrastructure.repositories.events import SqlAlchemyEventRepository
from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.infrastructure.repositories.ingestion_recovery import (
    SqlAlchemyIngestionRunRecovery,
)
from andromeda.infrastructure.repositories.ingestion_retry import (
    SqlAlchemyIngestionRetryExecutor,
)
from andromeda.infrastructure.repositories.knowledge_candidates import (
    SqlAlchemyKnowledgeCandidateRepository,
)
from andromeda.infrastructure.repositories.knowledge_conflicts import (
    SqlAlchemyConflictGroupRepository,
)
from andromeda.infrastructure.repositories.knowledge_manual import (
    SqlAlchemyKnowledgeManualSubmissionRepository,
)
from andromeda.infrastructure.repositories.knowledge_manual_auth import (
    ConfiguredKnowledgeManualAuthorization,
    UniversityPolicySubmissionOnlyAuthorizer,
)
from andromeda.infrastructure.repositories.knowledge_manual_capture import (
    SqlAlchemyKnowledgeManualSnapshotCapture,
)
from andromeda.infrastructure.repositories.knowledge_review import (
    SqlAlchemyKnowledgeReviewActionRepository,
)
from andromeda.infrastructure.repositories.knowledge_review_identity import (
    SqlAlchemyKnowledgeReviewIdentityResolver,
)
from andromeda.infrastructure.repositories.knowledge_source_repository import (
    SqlAlchemyKnowledgeSourceRepository,
)
from andromeda.infrastructure.repositories.policy import SqlAlchemyPolicyRuleRepository
from andromeda.infrastructure.repositories.policy_refresh import (
    SqlAlchemyPolicyProjectionRefreshRepository,
)
from andromeda.infrastructure.repositories.proftest import (
    SqlAlchemyProftestCatalogRepository,
)
from andromeda.infrastructure.repositories.proftest_sessions import (
    SqlAlchemyProftestSessionRepository,
)
from andromeda.infrastructure.repositories.programs import SqlAlchemyProgramRepository
from andromeda.infrastructure.repositories.query_sessions import (
    SqlAlchemyQuerySessionRepository,
)
from andromeda.infrastructure.repositories.recommendations import (
    CatalogRecommendationRepository,
)
from andromeda.infrastructure.repositories.semantic_enrichment import (
    SqlAlchemySemanticEnrichmentRepository,
)
from andromeda.infrastructure.repositories.universities import (
    SqlAlchemyUniversityRepository,
)
from andromeda.infrastructure.repositories.university_admin import (
    SqlAlchemyUniversityAdminMembershipRepository,
)
from andromeda.infrastructure.repositories.university_catalog import (
    SqlAlchemyUniversityCatalogCanonicalReader,
    SqlAlchemyUniversityCatalogRepository,
)
from andromeda.infrastructure.repositories.university_events import (
    SqlAlchemyUniversityEditorialEventRepository,
)
from andromeda.infrastructure.repositories.user_profiles import (
    SqlAlchemyUserProfileRepository,
)
from andromeda.infrastructure.security.passwords import Argon2PasswordHasher
from andromeda.modules.admin_ops.services.ingestion_runs import IngestionRunService
from andromeda.modules.admission_benefits.repository.ports import AdmissionBenefitReader
from andromeda.modules.admission_benefits.services.admission_decision import (
    AdmissionDecisionService,
)
from andromeda.modules.admission_benefits.services.facade import (
    AdmissionBenefitCatalogService,
    AdmissionEligibilityService,
)
from andromeda.modules.admission_benefits.services.policy_evaluation import (
    AdmissionBenefitsPolicyEvaluationService,
)
from andromeda.modules.admission_fit.repository.ports import AdmissionFitDataReader
from andromeda.modules.admission_fit.services.admission_fit import AdmissionFitService
from andromeda.modules.admissions.repository.ports import AdmissionCycleRepository
from andromeda.modules.admissions.services.admissions import AdmissionService
from andromeda.modules.analytics.services.cache import AnalyticsResultCache
from andromeda.modules.analytics.services.executor import AnalyticsExecutor
from andromeda.modules.analytics.services.projection_builder import (
    ProgramProjectionBuilder,
    ProgramProjectionService,
)
from andromeda.modules.auth.services.authentication import AuthenticationService
from andromeda.modules.campus.repository.ports import CampusPointReader
from andromeda.modules.campus.services.campus import CampusService
from andromeda.modules.comparison.services.compare_programs import (
    CompareProgramsService,
)
from andromeda.modules.comparison.services.compare_summary import (
    ComparisonSummaryService,
)
from andromeda.modules.conversation.contracts.policy import DecisionPolicyPort
from andromeda.modules.conversation.services.assistant import AssistantService
from andromeda.modules.conversation.services.engine import ConversationEngine
from andromeda.modules.curricula.repository.ports import CurriculumReader
from andromeda.modules.decision.services.analytics import DecisionAnalyticsService
from andromeda.modules.decision.services.candidates import DecisionCandidatePipeline
from andromeda.modules.decision.services.decision import DecisionService
from andromeda.modules.disciplines.repository.ports import DisciplineReader
from andromeda.modules.entity_resolution.contracts.ports import BoundedCandidateSelector
from andromeda.modules.entity_resolution.services.hierarchical import (
    HierarchicalResolutionService,
)
from andromeda.modules.entity_resolution.services.resolvers import (
    CachedEntityCatalog,
    EntityResolverService,
)
from andromeda.modules.events.services.events import EventService
from andromeda.modules.knowledge.repository.ports import (
    ConflictGroupRepository,
    KnowledgeCandidateRepository,
    KnowledgeReviewActionRepository,
    KnowledgeReviewAuthorizer,
    KnowledgeSourceRepository,
)
from andromeda.modules.knowledge.services.manual_source_commands import (
    ManualSourceCommands,
)
from andromeda.modules.knowledge.services.review_workflow import (
    KnowledgeReviewIdentityResolver,
    KnowledgeReviewPolicyApprovalPort,
    KnowledgeReviewWorkflow,
)
from andromeda.modules.personal_route.services.personal_route import (
    PersonalRouteService,
)
from andromeda.modules.policy.repository.ports import (
    PolicyCapabilityAuthorizer,
    PolicyProjectionRefreshRepository,
    PolicyRuleRepository,
)
from andromeda.modules.policy.services.approval import PolicyApprovalCommandService
from andromeda.modules.policy.services.dependency_refresh import (
    PolicyDependencyRefreshService,
)
from andromeda.modules.policy.services.effective_rule_resolver import (
    EffectivePolicyResolver,
)
from andromeda.modules.policy.services.impact_analyzer import PolicyImpactAnalyzer
from andromeda.modules.policy.services.knowledge_review_adapter import (
    PolicyApprovalReviewAdapter,
)
from andromeda.modules.policy.services.manual_submission import (
    ManualPolicyCandidateCommands,
)
from andromeda.modules.policy.services.ports import (
    PolicyDomainImpactPort,
    PolicyDomainRuleReader,
    PolicyProjectionRefreshBuilder,
)
from andromeda.modules.policy.services.sandbox_evaluator import (
    PolicyHypotheticalSandbox,
)
from andromeda.modules.presentation.contracts.verbalization import (
    ResponseNaturalizerPort,
)
from andromeda.modules.presentation.services.rule_response_policy import (
    RuleBasedResponsePolicy,
)
from andromeda.modules.proftest.repository.ports import UserProfileRepository
from andromeda.modules.proftest.services.catalog import ProftestCatalogService

logger = logging.getLogger("andromeda.composition.container")


class _SystemPolicyClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


from andromeda.modules.proftest.services.profile_persistence import (
    UserProfilePersistenceService,
)
from andromeda.modules.proftest.services.proftest import ProftestService
from andromeda.modules.proftest.services.session import ProftestSessionService
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.modules.recommendations.services.current import (
    CurrentRecommendationService,
)
from andromeda.modules.recommendations.services.recommendations import (
    RecommendationService,
)
from andromeda.modules.semantic.services.classifier import RuleBasedSemanticClassifier
from andromeda.modules.semantic.services.enrichment import SemanticEnrichmentService
from andromeda.modules.universities.repository.ports import UniversityReader
from andromeda.modules.university_admin.repository.catalog_ports import (
    UniversityCatalogCanonicalReader,
    UniversityCatalogReader,
    UniversityCatalogWriter,
)
from andromeda.modules.university_admin.repository.event_ports import (
    UniversityEditorialEventReader,
    UniversityEditorialEventWriter,
)
from andromeda.modules.university_admin.repository.ports import (
    UniversityAdminAccessReader,
    UniversityMembershipWriter,
)
from andromeda.modules.university_admin.services.access import (
    UniversityAdminAccessService,
)
from andromeda.modules.university_admin.services.catalog import UniversityCatalogService
from andromeda.modules.university_admin.services.events import (
    UniversityEditorialEventService,
)
from andromeda.modules.university_admin.services.membership import (
    UniversityMembershipService,
)


@dataclass(frozen=True, slots=True)
class AndromedaContainer:
    """The single outer composition root for API and script-owned services.

    The container is deliberately infrastructure-aware. It is an outer-layer
    object: subject modules still receive typed ports and never import this
    class, SQLAlchemy models, or FastAPI dependencies.
    """

    engine: Engine
    settings: Settings
    analytics_cache: AnalyticsResultCache = field(default_factory=AnalyticsResultCache)
    _decision_policy_cache: DecisionPolicyPort | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _admission_candidate_selector_cache: BoundedCandidateSelector | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _admission_candidate_selector_built: bool = field(
        default=False, init=False, repr=False, compare=False
    )
    _presentation_naturalizer_cache: ResponseNaturalizerPort | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _presentation_naturalizer_built: bool = field(
        default=False, init=False, repr=False, compare=False
    )

    def program_reader(self, session: Session) -> ProgramReader:
        return SqlAlchemyProgramRepository(session)

    def university_reader(self, session: Session) -> UniversityReader:
        return SqlAlchemyUniversityRepository(session)

    def university_admin_membership_repository(
        self, session: Session
    ) -> SqlAlchemyUniversityAdminMembershipRepository:
        return SqlAlchemyUniversityAdminMembershipRepository(session)

    def university_admin_access_reader(
        self, session: Session
    ) -> UniversityAdminAccessReader:
        return self.university_admin_membership_repository(session)

    def university_admin_membership_writer(
        self, session: Session
    ) -> UniversityMembershipWriter:
        return self.university_admin_membership_repository(session)

    def university_admin_access_service(
        self, session: Session
    ) -> UniversityAdminAccessService:
        return UniversityAdminAccessService(
            self.university_admin_access_reader(session)
        )

    def university_membership_service(
        self, session: Session
    ) -> UniversityMembershipService:
        repository = self.university_admin_membership_repository(session)
        return UniversityMembershipService(repository, repository)

    def university_catalog_reader(self, session: Session) -> UniversityCatalogReader:
        return SqlAlchemyUniversityCatalogRepository(session)

    def university_catalog_writer(self, session: Session) -> UniversityCatalogWriter:
        return SqlAlchemyUniversityCatalogRepository(session)

    def university_catalog_canonical_reader(
        self, session: Session
    ) -> UniversityCatalogCanonicalReader:
        return SqlAlchemyUniversityCatalogCanonicalReader(session)

    def university_catalog_service(self, session: Session) -> UniversityCatalogService:
        repository = SqlAlchemyUniversityCatalogRepository(session)
        return UniversityCatalogService(
            repository, repository, self.university_catalog_canonical_reader(session)
        )

    def university_editorial_event_reader(
        self, session: Session
    ) -> UniversityEditorialEventReader:
        return SqlAlchemyUniversityEditorialEventRepository(session)

    def university_editorial_event_writer(
        self, session: Session
    ) -> UniversityEditorialEventWriter:
        return SqlAlchemyUniversityEditorialEventRepository(session)

    def university_editorial_event_service(
        self, session: Session
    ) -> UniversityEditorialEventService:
        repository = SqlAlchemyUniversityEditorialEventRepository(session)
        return UniversityEditorialEventService(
            repository,
            repository,
            self.university_catalog_reader(session),
            self.university_catalog_canonical_reader(session),
        )

    def curriculum_reader(self, session: Session) -> CurriculumReader:
        return SqlAlchemyCurriculumRepository(session)

    def discipline_reader(self, session: Session) -> DisciplineReader:
        return SqlAlchemyDisciplineRepository(session)

    def admission_reader(self, session: Session) -> SqlAlchemyAdmissionRepository:
        return SqlAlchemyAdmissionRepository(session)

    def admission_cycle_repository(self, session: Session) -> AdmissionCycleRepository:
        return SqlAlchemyAdmissionCycleRepository(session)

    def admission_service(self, session: Session) -> AdmissionService:
        return AdmissionService(
            self.program_reader(session), self.admission_reader(session)
        )

    def admission_fit_reader(self, session: Session) -> AdmissionFitDataReader:
        return SqlAlchemyAdmissionFitReader(
            self.program_reader(session), self.admission_reader(session)
        )

    def admission_fit_service(self, session: Session) -> AdmissionFitService:
        return AdmissionFitService(self.admission_fit_reader(session))

    def admission_benefit_repository(self, session: Session) -> AdmissionBenefitReader:
        return SqlAlchemyAdmissionBenefitsRepository(session)

    def admission_benefit_catalog_service(
        self, session: Session
    ) -> AdmissionBenefitCatalogService:
        return AdmissionBenefitCatalogService(
            self.admission_benefit_repository(session)
        )

    def admission_eligibility_service(
        self, session: Session
    ) -> AdmissionEligibilityService:
        return AdmissionEligibilityService(
            self.admission_benefit_repository(session),
            AdmissionDecisionService(),
            self.admission_reader(session),
        )

    def admission_benefits_policy_evaluator(
        self, session: Session
    ) -> AdmissionBenefitsPolicyEvaluationService:
        return AdmissionBenefitsPolicyEvaluationService(
            self.admission_benefit_repository(session),
            self.admission_reader(session),
            AdmissionDecisionService(),
        )

    def comparison_service(self, session: Session) -> CompareProgramsService:
        return CompareProgramsService(
            self.program_reader(session),
            self.curriculum_reader(session),
            self.discipline_reader(session),
        )

    def comparison_summary_service(self, session: Session) -> ComparisonSummaryService:
        return ComparisonSummaryService(
            self.comparison_service(session),
            self.program_reader(session),
            self.curriculum_reader(session),
        )

    def proftest_catalog_reader(
        self, session: Session
    ) -> SqlAlchemyProftestCatalogRepository:
        return SqlAlchemyProftestCatalogRepository(
            self.program_reader(session),
            self.curriculum_reader(session),
            self.discipline_reader(session),
            session=session,
        )

    def proftest_catalog_service(self, session: Session) -> ProftestCatalogService:
        return ProftestCatalogService(
            self.proftest_catalog_reader(session),
            projection_reader=SqlAlchemyProgramProjectionRepository(self.engine),
        )

    def user_profile_repository(
        self, session: Session
    ) -> SqlAlchemyUserProfileRepository:
        return SqlAlchemyUserProfileRepository(session)

    def profile_persistence_service(
        self, session: Session
    ) -> UserProfilePersistenceService:
        return UserProfilePersistenceService(
            self.user_profile_repository(session),
            ttl_seconds=self.settings.profile_ttl_seconds,
        )

    def current_user_profile_reader(self, session: Session) -> UserProfileRepository:
        return self.user_profile_repository(session)

    def recommendation_catalog_reader(
        self, session: Session
    ) -> CatalogRecommendationRepository:
        return CatalogRecommendationRepository(self.proftest_catalog_service(session))

    def recommendation_service(self, session: Session) -> RecommendationService:
        return RecommendationService(self.recommendation_catalog_reader(session))

    def decision_context_repository(
        self, session: Session
    ) -> SqlAlchemyDecisionContextRepository:
        return SqlAlchemyDecisionContextRepository(session)

    def decision_analytics_writer(
        self, session: Session
    ) -> SqlAlchemyDecisionAnalyticsRepository:
        return SqlAlchemyDecisionAnalyticsRepository(session)

    def decision_analytics_reader(
        self, session: Session
    ) -> SqlAlchemyDecisionAnalyticsRepository:
        return SqlAlchemyDecisionAnalyticsRepository(session)

    def decision_analytics_service(self, session: Session) -> DecisionAnalyticsService:
        return DecisionAnalyticsService(self.decision_analytics_writer(session))

    def decision_candidate_source(
        self, session: Session
    ) -> CatalogDecisionCandidateSource:
        return CatalogDecisionCandidateSource(
            self.program_reader(session),
            self.recommendation_catalog_reader(session),
            self.admission_reader(session),
            self.university_reader(session),
        )

    def decision_candidate_pipeline(
        self, session: Session
    ) -> DecisionCandidatePipeline:
        return DecisionCandidatePipeline(
            self.decision_candidate_source(session),
            self.recommendation_service(session),
            self.admission_fit_service(session),
        )

    def decision_service(self, session: Session) -> DecisionService:
        return DecisionService(
            self.decision_context_repository(session),
            self.program_reader(session),
            self.current_user_profile_reader(session),
            self.decision_candidate_pipeline(session),
            ttl_seconds=self.settings.profile_ttl_seconds,
            analytics=self.decision_analytics_service(session),
            profile_writer=self.profile_persistence_service(session),
        )

    def proftest_service(self, session: Session) -> ProftestService:
        return ProftestService(
            self.proftest_catalog_service(session),
            self.recommendation_service(session),
            profile_persistence=self.profile_persistence_service(session),
        )

    def proftest_session_repository(
        self, session: Session
    ) -> SqlAlchemyProftestSessionRepository:
        return SqlAlchemyProftestSessionRepository(session)

    def proftest_session_service(self, session: Session) -> ProftestSessionService:
        session_repository = self.proftest_session_repository(session)
        return ProftestSessionService(
            self.proftest_catalog_service(session),
            self.recommendation_service(session),
            session_repository,
            session_repository,
            profile_reader=self.current_user_profile_reader(session),
            ttl_seconds=self.settings.profile_ttl_seconds,
        )

    def current_recommendation_service(
        self, session: Session
    ) -> CurrentRecommendationService:
        return CurrentRecommendationService(
            self.current_user_profile_reader(session),
            self.recommendation_service(session),
        )

    def event_reader(self, session: Session) -> SqlAlchemyEventRepository:
        return SqlAlchemyEventRepository(session)

    def event_service(self, session: Session) -> EventService:
        return EventService(self.event_reader(session))

    def campus_point_reader(self, session: Session) -> CampusPointReader:
        return SqlAlchemyCampusPointRepository(session)

    def campus_service(self, session: Session) -> CampusService:
        return CampusService(self.campus_point_reader(session))

    def personal_route_service(self, session: Session) -> PersonalRouteService:
        return PersonalRouteService(
            self.current_recommendation_service(session),
            self.event_service(session),
            self.campus_service(session),
        )

    def account_repository(self, session: Session) -> SqlAlchemyAccountRepository:
        return SqlAlchemyAccountRepository(session)

    def auth_service(self, session: Session) -> AuthenticationService:
        return AuthenticationService(
            self.account_repository(session),
            Argon2PasswordHasher(),
            self.user_profile_repository(session),
            self.proftest_session_repository(session),
            self.decision_context_repository(session),
            password_min_length=self.settings.auth_password_min_length,
            session_ttl_seconds=self.settings.auth_session_ttl_seconds,
        )

    def ingestion_run_reader(self, session: Session) -> SqlAlchemyIngestionRunReader:
        return SqlAlchemyIngestionRunReader(session)

    def ingestion_retry_executor(self) -> SqlAlchemyIngestionRetryExecutor:
        return SqlAlchemyIngestionRetryExecutor(self.engine, self.settings.environment)

    def ingestion_run_recovery(self) -> SqlAlchemyIngestionRunRecovery:
        return SqlAlchemyIngestionRunRecovery(self.engine)

    def ingestion_run_service(self, session: Session) -> IngestionRunService:
        return IngestionRunService(
            self.ingestion_run_reader(session),
            self.ingestion_retry_executor(),
            self.ingestion_run_recovery(),
            stale_timeout_seconds=self.settings.ingestion_run_timeout_seconds,
        )

    def knowledge_source_repository(
        self, session: Session
    ) -> KnowledgeSourceRepository:
        return SqlAlchemyKnowledgeSourceRepository(session)

    def knowledge_candidate_repository(
        self, session: Session
    ) -> KnowledgeCandidateRepository:
        return SqlAlchemyKnowledgeCandidateRepository(session)

    def knowledge_conflict_repository(
        self, session: Session
    ) -> ConflictGroupRepository:
        return SqlAlchemyConflictGroupRepository(session)

    def knowledge_manual_commands(self, session: Session) -> ManualSourceCommands:
        return ManualSourceCommands(
            sources=SqlAlchemyKnowledgeSourceRepository(session),
            candidates=SqlAlchemyKnowledgeCandidateRepository(session),
            submissions=SqlAlchemyKnowledgeManualSubmissionRepository(session),
            authorizer=ConfiguredKnowledgeManualAuthorization(
                university_access=self.university_admin_access_service(session),
                source_steward_account_ids=self.settings.knowledge_source_steward_account_ids,
            ),
            capture=SqlAlchemyKnowledgeManualSnapshotCapture(self.engine, session),
            unit_of_work=session,
        )

    def manual_policy_candidate_commands(
        self, session: Session, *, actor_account_id: str, university_id: str
    ) -> ManualPolicyCandidateCommands:
        authorizer = UniversityPolicySubmissionOnlyAuthorizer(
            university_access=self.university_admin_access_service(session),
            actor_account_id=actor_account_id,
            university_id=university_id,
        )
        return ManualPolicyCandidateCommands(
            approval_commands=self.policy_approval_command_service(session, authorizer),
            authorizer=authorizer,
        )

    def knowledge_review_action_repository(
        self, session: Session
    ) -> KnowledgeReviewActionRepository:
        return SqlAlchemyKnowledgeReviewActionRepository(session)

    def knowledge_review_workflow(
        self,
        session: Session,
        authorizer: KnowledgeReviewAuthorizer,
        identity_resolver: KnowledgeReviewIdentityResolver | None = None,
        policy_authorizer: PolicyCapabilityAuthorizer | None = None,
    ) -> KnowledgeReviewWorkflow:
        policy_approval_port: KnowledgeReviewPolicyApprovalPort | None = None
        if policy_authorizer is not None:
            policy_approval_port = PolicyApprovalReviewAdapter(
                self.policy_approval_command_service(session, policy_authorizer)
            )
        return KnowledgeReviewWorkflow(
            candidates=SqlAlchemyKnowledgeCandidateRepository(session),
            actions=self.knowledge_review_action_repository(session),
            authorizer=authorizer,
            unit_of_work=session,
            identity_resolver=identity_resolver
            or SqlAlchemyKnowledgeReviewIdentityResolver(session),
            policy_approval_port=policy_approval_port,
        )

    def policy_rule_repository(self, session: Session) -> PolicyRuleRepository:
        return SqlAlchemyPolicyRuleRepository(session)

    def policy_domain_rule_readers(
        self, session: Session
    ) -> tuple[PolicyDomainRuleReader, ...]:
        return (
            *self.admission_benefit_policy_adapters(session),
            AdmissionsPolicyRuleReader(
                self.admission_reader(session),
                SqlAlchemyKnowledgeSourceRepository(session),
            ),
        )

    def policy_domain_impact_readers(
        self, session: Session
    ) -> tuple[PolicyDomainImpactPort, ...]:
        return (
            *self.admission_benefit_policy_adapters(session),
            AdmissionsPolicyRuleReader(
                self.admission_reader(session),
                SqlAlchemyKnowledgeSourceRepository(session),
            ),
        )

    def admission_benefit_policy_adapters(
        self, session: Session
    ) -> tuple[AdmissionBenefitsPolicyRuleReader, ...]:
        return (
            AdmissionBenefitsPolicyRuleReader(
                SqlAlchemyAdmissionBenefitsRepository(session),
                source_observations=SqlAlchemyKnowledgeSourceRepository(session),
            ),
        )

    def policy_impact_analyzer(self, session: Session) -> PolicyImpactAnalyzer:
        return PolicyImpactAnalyzer(
            domain_owners=self.policy_domain_impact_readers(session)
        )

    def policy_hypothetical_sandbox(
        self, session: Session
    ) -> PolicyHypotheticalSandbox:
        return PolicyHypotheticalSandbox(
            revisions=self.policy_rule_repository(session),
            admission_cycles=self.admission_cycle_repository(session),
            domain_readers=self.policy_domain_rule_readers(session),
            domain_impact_readers=self.policy_domain_impact_readers(session),
            clock=_SystemPolicyClock(),
        )

    def effective_policy_resolver(self, session: Session) -> EffectivePolicyResolver:
        return EffectivePolicyResolver(
            policies=self.policy_rule_repository(session),
            admission_cycles=self.admission_cycle_repository(session),
            domain_readers=self.policy_domain_rule_readers(session),
            clock=_SystemPolicyClock(),
        )

    def policy_approval_command_service(
        self,
        session: Session,
        authorizer: PolicyCapabilityAuthorizer,
    ) -> PolicyApprovalCommandService:
        return PolicyApprovalCommandService(
            repository=self.policy_rule_repository(session),
            authorizer=authorizer,
            unit_of_work=session,
            approval_conflicts=SqlAlchemyPolicyApprovalConflictReader(
                SqlAlchemyConflictGroupRepository(session)
            ),
        )

    def policy_approval_review_adapter(
        self,
        session: Session,
        authorizer: PolicyCapabilityAuthorizer,
    ) -> PolicyApprovalReviewAdapter:
        return PolicyApprovalReviewAdapter(
            self.policy_approval_command_service(session, authorizer)
        )

    def policy_projection_refresh_repository(
        self, session: Session
    ) -> PolicyProjectionRefreshRepository:
        return SqlAlchemyPolicyProjectionRefreshRepository(session)

    def policy_dependency_refresh_service(
        self,
        session: Session,
        builder: PolicyProjectionRefreshBuilder,
    ) -> PolicyDependencyRefreshService:
        return PolicyDependencyRefreshService(
            repository=self.policy_projection_refresh_repository(session),
            approved_rules=self.policy_rule_repository(session),
            builder=builder,
        )

    @property
    def semantic_enrichment(self) -> SemanticEnrichmentService:
        return SemanticEnrichmentService(
            RuleBasedSemanticClassifier(),
            SqlAlchemySemanticEnrichmentRepository(self.engine),
        )

    @property
    def ingestion(self) -> SqlAlchemyIngestionRepository:
        return SqlAlchemyIngestionRepository(
            self.engine,
            derived_refresh=self.derived_refresh,
        )

    @property
    def derived_refresh(self) -> SqlAlchemyDerivedRefreshAdapter:
        return SqlAlchemyDerivedRefreshAdapter(
            self.semantic_enrichment,
            self.program_projection_service,
        )

    @property
    def program_projection_service(self) -> ProgramProjectionService:
        semantic_store = SqlAlchemySemanticEnrichmentRepository(self.engine)
        return ProgramProjectionService(
            ProgramProjectionBuilder(),
            semantic_store,
            SqlAlchemyProgramProjectionRepository(self.engine),
            cache=self.analytics_cache,
        )

    def analytics_executor(self) -> AnalyticsExecutor:
        return AnalyticsExecutor(
            SqlAlchemyProgramProjectionRepository(self.engine),
            cache=self.analytics_cache,
            semantic_predicate_port=self.jevql_adapter(),
        )

    def jevql_adapter(self) -> JevQLAdapter | None:
        """Compose the real upstream Jevql client only when the feature is enabled."""

        if not self.settings.jevql_enabled:
            return None
        if self.settings.jevql_endpoint is None:
            config = JevQLConfig(
                mode=JevQLMode.EMBEDDED,
                timeout_seconds=self.settings.jev_timeout_seconds,
                max_rows=self.settings.jev_max_rows,
                max_chars_per_row=min(self.settings.jev_max_chars, 8000),
                max_concurrency=self.settings.jev_max_concurrency,
            )
        else:
            parsed = urlparse(self.settings.jevql_endpoint)
            host = parsed.hostname
            if host is None:
                raise ValueError("JEVQL_ENDPOINT must include a hostname")
            config = JevQLConfig(
                mode=JevQLMode.SHARED_SERVICE,
                timeout_seconds=self.settings.jev_timeout_seconds,
                max_rows=self.settings.jev_max_rows,
                max_chars_per_row=min(self.settings.jev_max_chars, 8000),
                max_concurrency=self.settings.jev_max_concurrency,
                shared_endpoint=self.settings.jevql_endpoint,
                shared_allowed_hosts=(host,),
                shared_bearer_token=self.settings.jevql_token,
            )
        logger.info(
            "jevql_composed mode=%s endpoint_configured=%s",
            config.mode.value,
            config.shared_endpoint is not None,
        )
        return JevQLAdapter(config=config)

    def entity_resolver(self, session: Session | None = None) -> EntityResolverService:
        return EntityResolverService(
            CachedEntityCatalog(SqlAlchemyEntityResolutionRepository(self.engine)),
            hierarchical=self.jev_tree_resolver(),
            admission_benefit_reader=(
                self.admission_benefit_repository(session)
                if session is not None
                else None
            ),
            candidate_selector=self.admission_candidate_selector(),
        )

    def admission_candidate_selector(self) -> BoundedCandidateSelector | None:
        if not self._admission_candidate_selector_built:
            selector, _ = build_admission_candidate_selector(self.settings)
            object.__setattr__(self, "_admission_candidate_selector_cache", selector)
            object.__setattr__(self, "_admission_candidate_selector_built", True)
        return self._admission_candidate_selector_cache

    def jev_tree_resolver(self) -> HierarchicalResolutionService | None:
        """Compose jev-tree only for large candidate sets when explicitly enabled."""

        if not self.settings.jev_tree_enabled:
            return None
        bridge_path = (
            Path(__file__).resolve().parents[3]
            / "jev-tree-bridge"
            / "src"
            / "index.mjs"
        )
        config = JevTreeConfig(
            enabled=True,
            bridge_path=bridge_path,
            timeout_seconds=min(self.settings.jev_timeout_seconds, 15.0),
        )
        logger.info("jev_tree_composed bridge=%s threshold=%d", bridge_path.name, 255)
        return HierarchicalResolutionService(
            JevTreeAdapter(NodeJevTreeTransport(config)),
            candidate_threshold=255,
            timeout_seconds=config.timeout_seconds,
        )

    def assistant_service(self, session: Session) -> AssistantService:
        return AssistantService(
            SqlAlchemyQuerySessionRepository(session),
            ConversationEngine(),
            self.decision_policy(),
            RuleBasedResponsePolicy(),
            self.analytics_executor(),
            self.admission_fit_service(session),
            self.program_reader(session),
            entity_resolver=self.entity_resolver(session),
            policy_resolver=self.effective_policy_resolver(session),
            claim_lookup=self.knowledge_candidate_repository(session),
            admission_benefit_policy_evaluator=self.admission_benefits_policy_evaluator(
                session
            ),
            knowledge_naturalizer=self.presentation_naturalizer(),
            knowledge_policy_enabled=self.settings.knowledge_policy_assistant_enabled,
            ttl_seconds=self.settings.profile_ttl_seconds,
        )

    def decision_policy(self) -> DecisionPolicyPort:
        if self._decision_policy_cache is None:
            built_policy, _ = build_decision_policy(self.settings)
            object.__setattr__(self, "_decision_policy_cache", built_policy)
        cached_policy = self._decision_policy_cache
        assert cached_policy is not None
        return cached_policy

    def presentation_naturalizer(self) -> ResponseNaturalizerPort | None:
        """Compose an optional prose provider without making it a core dependency."""

        if (
            not self.settings.presentation_llm_enabled
            or not self.settings.polza_api_key
        ):
            return None
        if not self._presentation_naturalizer_built:
            naturalizer: ResponseNaturalizerPort = PolzaNaturalizer(self.settings)
            object.__setattr__(self, "_presentation_naturalizer_cache", naturalizer)
            object.__setattr__(self, "_presentation_naturalizer_built", True)
            logger.info(
                "presentation_naturalizer_composed provider=polza model=%s",
                self.settings.deepseek_model,
            )
        return self._presentation_naturalizer_cache


def build_container(
    engine: Engine, settings: Settings | None = None
) -> AndromedaContainer:
    """Build the only active service graph for an application process."""

    return AndromedaContainer(
        engine=engine, settings=settings or Settings.from_environment()
    )


__all__ = ["AndromedaContainer", "build_container"]
