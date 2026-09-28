"""Exact canonical identity validation for human-reviewed source claims."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    DirectionModel,
    EducationalProgramModel,
    UniversityModel,
)
from andromeda.modules.knowledge.contracts.public import Claim, ClaimSubjectKind
from andromeda.shared.contracts.errors import ValidationError


class SqlAlchemyKnowledgeReviewIdentityResolver:
    """Allow only existing catalog IDs whose table matches the typed claim subject."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def require_exact_identity(self, canonical_id: str, *, claim: Claim) -> None:
        proposition = claim.proposition
        if proposition is None:
            raise ValidationError("identity resolution requires a typed source claim")
        if proposition.subject_kind is ClaimSubjectKind.UNIVERSITY:
            identity_query = select(UniversityModel.id)
        elif proposition.subject_kind is ClaimSubjectKind.DIRECTION:
            identity_query = select(DirectionModel.id)
        elif proposition.subject_kind is ClaimSubjectKind.PROGRAM:
            identity_query = select(EducationalProgramModel.id)
        else:
            raise ValidationError(
                "this subject kind has no registered canonical identity catalog"
            )
        exists = self._session.scalar(
            identity_query.where(identity_query.selected_columns[0] == canonical_id).limit(1)
        )
        if exists is None:
            raise ValidationError(
                "identity resolution must select an existing exact canonical ID"
            )


__all__ = ["SqlAlchemyKnowledgeReviewIdentityResolver"]
