"""Explicit client-facing v1 aliases for the existing FastAPI operations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRouter
from fastapi.routing import APIRoute

from andromeda.api.dependencies.auth_session import (
    get_optional_current_account,
    require_current_account,
)
from andromeda.api.dependencies.profile_session import (
    get_anonymous_profile_scope,
    get_profile_scope,
)
from andromeda.infrastructure.config.settings import (
    DEFAULT_AUTH_COOKIE_NAME,
    DEFAULT_PROFILE_COOKIE_NAME,
)

RouteKey = tuple[str, str]

# Deliberately explicit: adding an operation to a router does not make it public.
PUBLIC_API_V1_OPERATIONS: frozenset[RouteKey] = frozenset(
    {
        ("GET", "/admission-benefits/olympiads/{olympiad_id}/programs"),
        ("GET", "/universities/{university_id}/admission-benefits"),
        ("GET", "/programs/{program_id}/admission-benefits"),
        ("POST", "/programs/{program_id}/admission-eligibility"),
        ("POST", "/analytics/query"),
        ("POST", "/assistant/query"),
        ("POST", "/auth/decision/import-guest"),
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/register"),
        ("GET", "/auth/session"),
        ("GET", "/campus/points"),
        ("GET", "/campus/points/{id}"),
        ("GET", "/campus/points/{id}/events"),
        ("GET", "/campus/recommendations"),
        ("GET", "/compare"),
        ("GET", "/compare/summary"),
        ("GET", "/discipline-areas"),
        ("POST", "/decision/analytics"),
        ("GET", "/decision/context"),
        ("GET", "/decision/suggestions"),
        ("POST", "/decision/refinement/answer"),
        ("PUT", "/decision/constraints"),
        ("POST", "/decision/considered"),
        ("POST", "/decision/shortlist"),
        ("PATCH", "/decision/shortlist/{program_id}"),
        ("POST", "/decision/final-choice"),
        ("DELETE", "/decision/final-choice"),
        ("DELETE", "/decision/shortlist/{program_id}"),
        ("POST", "/decision/programs/{program_id}/restore"),
        ("POST", "/decision/programs/{program_id}/exclude"),
        ("DELETE", "/decision/programs/{program_id}/exclude"),
        ("POST", "/decision/suggestions/{program_id}/accept"),
        ("POST", "/decision/suggestions/{program_id}/reject"),
        ("GET", "/events"),
        ("GET", "/events/{id}"),
        ("GET", "/health/live"),
        ("GET", "/personal-route"),
        ("POST", "/proftest/analytics"),
        ("GET", "/proftest/profile"),
        ("POST", "/proftest/profile"),
        ("PUT", "/proftest/profile"),
        ("POST", "/proftest/sessions"),
        ("GET", "/proftest/sessions/current"),
        ("PATCH", "/proftest/sessions/current"),
        ("POST", "/proftest/sessions/current/complete"),
        ("POST", "/proftest/sessions/current/next"),
        ("GET", "/programs"),
        ("GET", "/programs/{id}"),
        ("POST", "/programs/{id}/admission-fit"),
        ("GET", "/programs/{id}/admissions"),
        ("GET", "/programs/{id}/curriculum"),
        ("POST", "/recommendations"),
        ("GET", "/recommendations/current"),
        ("GET", "/universities"),
        ("GET", "/universities/{university_id}/catalog"),
        ("GET", "/universities/{university_id}/events"),
        ("GET", "/universities/{university_id}/events/{event_id}"),
    }
)

_PUBLIC_API_V1_PREFIX = "/api/v1"
_HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
)
_PROFILE_COOKIE_SCHEME = "AndromedaProfileSession"
_AUTH_COOKIE_SCHEME = "AndromedaAuthSession"


def register_public_api_v1_routes(
    app: FastAPI, source_routers: Iterable[APIRouter]
) -> None:
    """Register aliases of allowlisted routes and fail closed on manifest drift."""

    routes_by_key: dict[RouteKey, list[APIRoute]] = defaultdict(list)
    for router in source_routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods or ():
                routes_by_key[(method.upper(), route.path)].append(route)

    missing = sorted(PUBLIC_API_V1_OPERATIONS - routes_by_key.keys())
    duplicated = sorted(
        key
        for key in PUBLIC_API_V1_OPERATIONS
        if len(routes_by_key.get(key, ())) != 1
    )
    if missing or duplicated:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if duplicated:
            details.append(f"duplicated={duplicated}")
        raise RuntimeError(
            "Public API v1 route manifest does not match source routers: "
            + "; ".join(details)
        )

    operation_ids: set[str] = set()
    for method, source_path in sorted(PUBLIC_API_V1_OPERATIONS):
        source = routes_by_key[(method, source_path)][0]
        if not source.include_in_schema:
            raise RuntimeError(
                "Public API v1 manifest includes a route hidden from OpenAPI: "
                f"{method} {source_path}"
            )

        operation_id = f"public_v1_{source.unique_id}"
        if operation_id in operation_ids:
            raise RuntimeError(
                f"Duplicate Public API v1 operation ID: {operation_id}"
            )
        operation_ids.add(operation_id)

        openapi_extra = dict(source.openapi_extra or {})
        openapi_extra.update(
            {
                "x-andromeda-api-surface": "public",
                "x-andromeda-api-version": 1,
            }
        )
        alias = type(source)(
            path=f"/api/v1{source_path}",
            endpoint=source.endpoint,
            response_model=source.response_model,
            status_code=source.status_code,
            tags=list(dict.fromkeys([*(app.router.tags or ()), *(source.tags or ())])),
            dependencies=[
                *(app.router.dependencies or ()),
                *(source.dependencies or ()),
            ],
            summary=source.summary,
            description=source.description,
            response_description=source.response_description,
            responses={
                **(app.router.responses or {}),
                **(source.responses or {}),
            },
            deprecated=source.deprecated,
            methods=[method],
            operation_id=operation_id,
            response_model_include=source.response_model_include,
            response_model_exclude=source.response_model_exclude,
            response_model_by_alias=source.response_model_by_alias,
            response_model_exclude_unset=source.response_model_exclude_unset,
            response_model_exclude_defaults=source.response_model_exclude_defaults,
            response_model_exclude_none=source.response_model_exclude_none,
            include_in_schema=source.include_in_schema,
            response_class=source.response_class,
            name=f"public_v1_{source.name}_{method.lower()}",
            openapi_extra=openapi_extra,
            callbacks=list(source.callbacks or ()),
            dependency_overrides_provider=app,
            generate_unique_id_function=source.generate_unique_id_function,
            strict_content_type=source.strict_content_type,
        )
        app.router.routes.append(alias)


def project_public_api_v1_openapi(app: FastAPI) -> dict[str, Any]:
    """Return a public-only OpenAPI projection of this app's full contract."""

    full_document = app.openapi()
    route_by_key = {
        (method.upper(), route.path.removeprefix(_PUBLIC_API_V1_PREFIX)): route
        for route in app.router.routes
        if isinstance(route, APIRoute)
        and route.path.startswith(f"{_PUBLIC_API_V1_PREFIX}/")
        for method in route.methods or ()
    }
    if set(route_by_key) != PUBLIC_API_V1_OPERATIONS:
        missing = sorted(PUBLIC_API_V1_OPERATIONS - route_by_key.keys())
        unexpected = sorted(route_by_key.keys() - PUBLIC_API_V1_OPERATIONS)
        raise RuntimeError(
            "Registered Public API v1 routes differ from the public manifest: "
            f"missing={missing}; unexpected={unexpected}"
        )

    document = deepcopy(full_document)
    public_paths: dict[str, dict[str, Any]] = {}
    for method, source_path in sorted(PUBLIC_API_V1_OPERATIONS):
        public_path = f"{_PUBLIC_API_V1_PREFIX}{source_path}"
        source_path_item = full_document["paths"].get(public_path)
        if not isinstance(source_path_item, dict):
            raise RuntimeError(f"Public API v1 operation missing from OpenAPI: {method} {public_path}")
        path_item = public_paths.setdefault(public_path, {})
        operation = source_path_item.get(method.lower())
        if not isinstance(operation, dict):
            raise RuntimeError(f"Public API v1 operation missing from OpenAPI: {method} {public_path}")
        path_item[method.lower()] = deepcopy(operation)
        if "parameters" in source_path_item:
            path_item["parameters"] = deepcopy(source_path_item["parameters"])
        _set_operation_cookie_security(
            path_item[method.lower()], route_by_key[(method, source_path)]
        )

    document["paths"] = public_paths
    document.pop("security", None)
    if isinstance(document.get("tags"), list):
        public_tags = {
            tag
            for path_item in public_paths.values()
            for method, operation in path_item.items()
            if method in _HTTP_METHODS
            for tag in operation.get("tags", [])
        }
        document["tags"] = [
            tag for tag in document["tags"] if tag.get("name") in public_tags
        ]
    document["info"] = {
        **document.get("info", {}),
        "title": "Andromeda Public API",
        "version": "1.0.0",
        "description": (
            "Stable Public API v1 for Andromeda user-facing transports such as Web, "
            "MAX Bot and MAX Mini App. Operator, review and university administration "
            "operations are documented only by the full application OpenAPI."
        ),
        "x-andromeda-session-contract": {
            "profileCookie": {
                "name": getattr(
                    app.state.settings, "profile_cookie_name", DEFAULT_PROFILE_COOKIE_NAME
                ),
                "optional": True,
                "purpose": "Opaque guest profile scope; the server may issue it when absent.",
            },
            "authCookie": {
                "name": getattr(
                    app.state.settings, "auth_cookie_name", DEFAULT_AUTH_COOKIE_NAME
                ),
                "optionalByDefault": True,
                "purpose": "Opaque account session; account-only operations declare it required.",
            },
            "revisionConflicts": "HTTP 409 with the standard ErrorResponse envelope.",
        },
        "x-andromeda-list-contract": {
            f"{_PUBLIC_API_V1_PREFIX}/universities": "unpaginated items collection",
            f"{_PUBLIC_API_V1_PREFIX}/programs": "unpaginated items collection",
        },
    }

    _omit_inert_assistant_interactive_field(document)
    components = document.get("components")
    if isinstance(components, dict):
        components["securitySchemes"] = {
            _PROFILE_COOKIE_SCHEME: {
                "type": "apiKey",
                "in": "cookie",
                "name": document["info"]["x-andromeda-session-contract"]["profileCookie"]["name"],
                "description": "Optional opaque guest profile cookie; never a platform user ID.",
            },
            _AUTH_COOKIE_SCHEME: {
                "type": "apiKey",
                "in": "cookie",
                "name": document["info"]["x-andromeda-session-contract"]["authCookie"]["name"],
                "description": "Opaque authenticated account session cookie.",
            },
        }
        _prune_components(document)

    return document


def _set_operation_cookie_security(operation: dict[str, Any], route: APIRoute) -> None:
    calls = tuple(_dependency_calls(route.dependant))
    if any(call is require_current_account for call in calls):
        operation["security"] = [{_AUTH_COOKIE_SCHEME: []}]
        return

    requirements: list[dict[str, list[Any]]] = []
    if any(
        call is get_profile_scope or call is get_anonymous_profile_scope
        for call in calls
    ):
        requirements.append({_PROFILE_COOKIE_SCHEME: []})
    if any(call is get_optional_current_account for call in calls):
        requirements.append({_AUTH_COOKIE_SCHEME: []})
    if requirements:
        operation["security"] = [*requirements, {}]


def _dependency_calls(dependant: Dependant) -> Iterable[Any]:
    if dependant.call is not None:
        yield dependant.call
    for child in dependant.dependencies:
        yield from _dependency_calls(child)


def _omit_inert_assistant_interactive_field(document: dict[str, Any]) -> None:
    request_schema = (
        document["paths"][f"{_PUBLIC_API_V1_PREFIX}/assistant/query"]["post"]
        .get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    reference = request_schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/components/schemas/"):
        raise RuntimeError("Public assistant request schema reference is missing")
    schema_name = reference.rsplit("/", 1)[-1]
    schema = document["components"]["schemas"].get(schema_name)
    if not isinstance(schema, dict):
        raise RuntimeError(f"Public assistant request schema is missing: {schema_name}")
    properties = schema.get("properties")
    if isinstance(properties, dict):
        properties.pop("interactive", None)
    required = schema.get("required")
    if isinstance(required, list) and "interactive" in required:
        required.remove("interactive")


def _component_references(value: Any) -> set[tuple[str, str]]:
    references: set[tuple[str, str]] = set()
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/components/"):
            parts = reference.removeprefix("#/components/").split("/", 1)
            if len(parts) == 2:
                component_name = parts[1].replace("~1", "/").replace("~0", "~")
                references.add((parts[0], component_name))
        for nested in value.values():
            references.update(_component_references(nested))
    elif isinstance(value, list):
        for nested in value:
            references.update(_component_references(nested))
    return references


def _prune_components(document: dict[str, Any]) -> None:
    components = document.get("components")
    if not isinstance(components, dict):
        return

    selected: dict[str, set[str]] = defaultdict(set)
    security_schemes = {
        scheme_name
        for path_item in document["paths"].values()
        for method, operation in path_item.items()
        if method in _HTTP_METHODS and isinstance(operation, dict)
        for requirement in operation.get("security", [])
        for scheme_name in requirement
    }
    selected["securitySchemes"].update(security_schemes)
    pending = list(_component_references(document["paths"]))
    while pending:
        component_type, component_name = pending.pop()
        component_group = components.get(component_type)
        if (
            not isinstance(component_group, dict)
            or component_name not in component_group
            or component_name in selected[component_type]
        ):
            continue
        selected[component_type].add(component_name)
        pending.extend(_component_references(component_group[component_name]))

    document["components"] = {
        component_type: {
            name: value
            for name, value in component_group.items()
            if name in selected.get(component_type, set())
        }
        for component_type, component_group in components.items()
        if isinstance(component_group, dict)
        and selected.get(component_type, set())
    }


__all__ = [
    "PUBLIC_API_V1_OPERATIONS",
    "project_public_api_v1_openapi",
    "register_public_api_v1_routes",
]
