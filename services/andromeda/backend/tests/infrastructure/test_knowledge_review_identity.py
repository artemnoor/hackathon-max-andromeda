from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import UniversityModel
from andromeda.infrastructure.repositories.knowledge_review_identity import (
    SqlAlchemyKnowledgeReviewIdentityResolver,
)
from andromeda.modules.knowledge.contracts.public import ClaimSubjectKind
from andromeda.shared.contracts.errors import ValidationError


def _claim(subject_kind: ClaimSubjectKind) -> SimpleNamespace:
    return SimpleNamespace(proposition=SimpleNamespace(subject_kind=subject_kind))


def test_identity_review_accepts_only_existing_subject_kind_specific_ids() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                UniversityModel(
                    id="university:bmstu",
                    name="BMSTU",
                    city="Moscow",
                    official_site="https://bmstu.ru",
                    address="Moscow",
                )
            )
            session.flush()
            resolver = SqlAlchemyKnowledgeReviewIdentityResolver(session)

            resolver.require_exact_identity(
                "university:bmstu", claim=_claim(ClaimSubjectKind.UNIVERSITY)  # type: ignore[arg-type]
            )
            with pytest.raises(ValidationError, match="existing exact canonical ID"):
                resolver.require_exact_identity(
                    "university:missing", claim=_claim(ClaimSubjectKind.UNIVERSITY)  # type: ignore[arg-type]
                )
            with pytest.raises(ValidationError, match="no registered canonical identity"):
                resolver.require_exact_identity(
                    "olympiad:example", claim=_claim(ClaimSubjectKind.OLYMPIAD)  # type: ignore[arg-type]
                )
    finally:
        engine.dispose()
