from __future__ import annotations

from andromeda.api.main import create_app
from andromeda.modules.admission_fit.contracts.public import AdmissionFitRequest, BatchAdmissionFitRequest
from andromeda.modules.admissions.contracts.public import AdmissionOffering
from andromeda.modules.comparison.contracts.requests import ComparisonRequest, ComparisonSummaryRequest
from andromeda.modules.decision.contracts.public import DecisionContext
from andromeda.modules.proftest.contracts.public import ProfileScope, ProgramFingerprint


REQUIRED_ROUTE_METHODS = {
    "/compare": {"get"},
    "/compare/summary": {"get"},
    "/programs/{id}/curriculum": {"get"},
    "/programs/{id}/admissions": {"get"},
    "/programs/{id}/admission-fit": {"post"},
    "/recommendations": {"post"},
    "/decision/context": {"get"},
    "/decision/suggestions": {"get"},
    "/events": {"get"},
    "/universities": {"get"},
}


def test_existing_public_contract_imports_remain_available() -> None:
    contracts = (
        AdmissionFitRequest,
        BatchAdmissionFitRequest,
        AdmissionOffering,
        ComparisonRequest,
        ComparisonSummaryRequest,
        DecisionContext,
        ProfileScope,
        ProgramFingerprint,
    )
    assert all(contract.model_config.get("extra") == "forbid" for contract in contracts)


def test_existing_api_routes_remain_compatibility_obligations() -> None:
    routes = create_app("sqlite://").openapi()["paths"]
    for path, methods in REQUIRED_ROUTE_METHODS.items():
        assert path in routes
        assert methods <= set(routes[path])
