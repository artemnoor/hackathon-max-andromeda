from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from andromeda.composition import AndromedaContainer
from andromeda.modules.admin_ops.repository.ports import (
    IngestionRetryExecutor,
    IngestionRunReader,
)
from andromeda.modules.admin_ops.services.ingestion_runs import IngestionRunService
from andromeda.modules.admission_fit.repository.ports import AdmissionFitDataReader
from andromeda.modules.admission_fit.services.admission_fit import AdmissionFitService
from andromeda.modules.admission_benefits.repository.ports import AdmissionBenefitReader
from andromeda.modules.admission_benefits.services.facade import (
    AdmissionBenefitCatalogService,
    AdmissionEligibilityService,
)
from andromeda.modules.admissions.repository.ports import AdmissionReader
from andromeda.modules.admissions.services.admissions import AdmissionService
from andromeda.modules.analytics.services.executor import AnalyticsExecutor
from andromeda.modules.conversation.services.assistant import AssistantService
from andromeda.modules.auth.services.authentication import AuthenticationService
from andromeda.modules.campus.repository.ports import CampusPointReader
from andromeda.modules.campus.services.campus import CampusService
from andromeda.modules.comparison.services.compare_programs import (
    CompareProgramsService,
)
from andromeda.modules.comparison.services.compare_summary import (
    ComparisonSummaryService,
)
from andromeda.modules.curricula.repository.ports import CurriculumReader
from andromeda.modules.decision.repository.ports import (
    DecisionAnalyticsReader,
    DecisionAnalyticsWriter,
    DecisionBindingPort,
    DecisionContextRepository,
    ProgramCandidateSource,
)
from andromeda.modules.decision.services.analytics import DecisionAnalyticsService
from andromeda.modules.decision.services.candidates import DecisionCandidatePipeline
from andromeda.modules.decision.services.decision import DecisionService
from andromeda.modules.disciplines.repository.ports import DisciplineReader
from andromeda.modules.events.repository.ports import EventReader
from andromeda.modules.events.services.events import EventService
from andromeda.modules.personal_route.services.personal_route import (
    PersonalRouteService,
)
from andromeda.modules.proftest.contracts.public import CurrentUserProfileReader
from andromeda.modules.proftest.repository.ports import (
    ProfileBindingPort,
    ProftestAnswerSessionRepository,
    ProftestCatalogReader,
    ProftestSessionBindingPort,
    UserProfileRepository,
)
from andromeda.modules.proftest.services.catalog import ProftestCatalogService
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
from andromeda.modules.universities.repository.ports import UniversityReader
from andromeda.modules.university_admin.repository.catalog_ports import (
    UniversityCatalogCanonicalReader,
    UniversityCatalogReader,
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

from .composition import get_composition_root
from .request_context import get_session


def get_program_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ProgramReader:
    return container.program_reader(session)


def get_university_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> UniversityReader:
    return container.university_reader(session)


def get_university_admin_access_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> UniversityAdminAccessService:
    return container.university_admin_access_service(session)


def get_university_membership_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> UniversityMembershipService:
    return container.university_membership_service(session)


def get_university_catalog_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> UniversityCatalogReader:
    return container.university_catalog_reader(session)


def get_university_catalog_canonical_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> UniversityCatalogCanonicalReader:
    return container.university_catalog_canonical_reader(session)


def get_university_catalog_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> UniversityCatalogService:
    return container.university_catalog_service(session)


def get_university_editorial_event_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> UniversityEditorialEventService:
    return container.university_editorial_event_service(session)


def get_curriculum_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> CurriculumReader:
    return container.curriculum_reader(session)


def get_discipline_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> DisciplineReader:
    return container.discipline_reader(session)


def get_admission_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> AdmissionReader:
    return container.admission_reader(session)


def get_admission_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> AdmissionService:
    return container.admission_service(session)


def get_admission_fit_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> AdmissionFitDataReader:
    return container.admission_fit_reader(session)


def get_admission_fit_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> AdmissionFitService:
    return container.admission_fit_service(session)


def get_admission_benefit_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> AdmissionBenefitReader:
    return container.admission_benefit_repository(session)


def get_admission_benefit_catalog_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> AdmissionBenefitCatalogService:
    return container.admission_benefit_catalog_service(session)


def get_admission_eligibility_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> AdmissionEligibilityService:
    return container.admission_eligibility_service(session)


def get_analytics_executor(
    container: AndromedaContainer = Depends(get_composition_root),
) -> AnalyticsExecutor:
    return container.analytics_executor()


def get_assistant_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> AssistantService:
    return container.assistant_service(session)


def get_compare_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> CompareProgramsService:
    return container.comparison_service(session)


def get_compare_summary_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ComparisonSummaryService:
    return container.comparison_summary_service(session)


def get_proftest_catalog_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ProftestCatalogReader:
    return container.proftest_catalog_reader(session)


def get_proftest_catalog_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ProftestCatalogService:
    return container.proftest_catalog_service(session)


def get_user_profile_repository(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> UserProfileRepository:
    return container.user_profile_repository(session)


def get_profile_binding_port(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ProfileBindingPort:
    return container.user_profile_repository(session)


def get_proftest_session_binding_port(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ProftestSessionBindingPort:
    return container.proftest_session_repository(session)


def get_decision_context_repository(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> DecisionContextRepository:
    return container.decision_context_repository(session)


def get_decision_binding_port(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> DecisionBindingPort:
    return container.decision_context_repository(session)


def get_auth_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> AuthenticationService:
    return container.auth_service(session)


def get_profile_persistence_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> UserProfilePersistenceService:
    return container.profile_persistence_service(session)


def get_current_user_profile_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> CurrentUserProfileReader:
    return container.current_user_profile_reader(session)


def get_recommendation_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> RecommendationService:
    return container.recommendation_service(session)


def get_decision_candidate_source(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ProgramCandidateSource:
    return container.decision_candidate_source(session)


def get_decision_candidate_pipeline(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> DecisionCandidatePipeline:
    return container.decision_candidate_pipeline(session)


def get_decision_analytics_writer(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> DecisionAnalyticsWriter:
    return container.decision_analytics_writer(session)


def get_decision_analytics_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> DecisionAnalyticsReader:
    return container.decision_analytics_reader(session)


def get_decision_analytics_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> DecisionAnalyticsService:
    return container.decision_analytics_service(session)


def get_decision_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> DecisionService:
    return container.decision_service(session)


def get_proftest_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ProftestService:
    return container.proftest_service(session)


def get_proftest_session_repository(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ProftestAnswerSessionRepository:
    return container.proftest_session_repository(session)


def get_proftest_session_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> ProftestSessionService:
    return container.proftest_session_service(session)


def get_current_recommendation_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> CurrentRecommendationService:
    return container.current_recommendation_service(session)


def get_event_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> EventReader:
    return container.event_reader(session)


def get_event_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> EventService:
    return container.event_service(session)


def get_campus_point_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> CampusPointReader:
    return container.campus_point_reader(session)


def get_campus_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> CampusService:
    return container.campus_service(session)


def get_personal_route_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> PersonalRouteService:
    return container.personal_route_service(session)


def get_ingestion_run_reader(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> IngestionRunReader:
    return container.ingestion_run_reader(session)


def get_ingestion_retry_executor(
    container: AndromedaContainer = Depends(get_composition_root),
) -> IngestionRetryExecutor:
    return container.ingestion_retry_executor()


def get_ingestion_run_service(
    container: AndromedaContainer = Depends(get_composition_root),
    session: Session = Depends(get_session),
) -> IngestionRunService:
    return container.ingestion_run_service(session)
