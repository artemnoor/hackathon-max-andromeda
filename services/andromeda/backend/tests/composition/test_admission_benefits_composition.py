from pathlib import Path

from sqlalchemy.orm import Session

from andromeda.composition import AndromedaContainer
from andromeda.infrastructure.config.settings import Settings
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.modules.admission_benefits.services.facade import AdmissionBenefitCatalogService, AdmissionEligibilityService


def test_composition_exposes_typed_admission_benefit_services(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'composition.db').as_posix()}")
    Base.metadata.create_all(engine)
    container = AndromedaContainer(engine=engine, settings=Settings.from_environment(f"sqlite:///{(tmp_path / 'composition.db').as_posix()}"))
    with Session(engine) as session:
        assert isinstance(container.admission_benefit_catalog_service(session), AdmissionBenefitCatalogService)
        assert isinstance(container.admission_eligibility_service(session), AdmissionEligibilityService)
    engine.dispose()
