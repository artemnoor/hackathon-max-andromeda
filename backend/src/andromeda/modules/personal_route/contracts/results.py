"""Application result envelope for personal-plan consumers."""

from __future__ import annotations

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel

from .public import PersonalRoutePlan


class PersonalRouteResult(ContractModel):
    plan: PersonalRoutePlan = Field(...)


__all__ = ["PersonalRouteResult"]
