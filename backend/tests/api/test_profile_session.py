from __future__ import annotations

from http.cookies import SimpleCookie

from fastapi import Request, Response

from andromeda.api.dependencies.profile_session import resolve_profile_scope
from andromeda.infrastructure.config import Settings


def _request(cookie: str | None = None) -> Request:
    headers = [] if cookie is None else [(b"cookie", cookie.encode("ascii"))]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proftest/profile",
            "raw_path": b"/proftest/profile",
            "query_string": b"",
            "headers": headers,
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
        }
    )


def test_missing_cookie_gets_hash_only_scope_and_secure_cookie_attributes() -> None:
    settings = Settings(profile_cookie_secure=True, profile_cookie_max_age=3600, profile_ttl_seconds=3600)
    response = Response()

    scope = resolve_profile_scope(_request(), response, settings)

    assert len(scope.session_key_hash) == 64
    assert "session_key_hash" not in response.headers.get("set-cookie", "")
    cookie = SimpleCookie(response.headers["set-cookie"])[settings.profile_cookie_name]
    assert cookie["httponly"]
    assert cookie["secure"]
    assert cookie["samesite"].lower() == "lax"
    assert cookie["max-age"] == "3600"


def test_same_cookie_resolves_to_same_scope_without_issuing_a_new_cookie() -> None:
    settings = Settings()
    first_response = Response()
    resolve_profile_scope(_request(), first_response, settings)
    cookie = SimpleCookie(first_response.headers["set-cookie"])[settings.profile_cookie_name].value

    second_response = Response()
    second_scope = resolve_profile_scope(_request(f"{settings.profile_cookie_name}={cookie}"), second_response, settings)
    third_response = Response()
    third_scope = resolve_profile_scope(_request(f"{settings.profile_cookie_name}={cookie}"), third_response, settings)

    assert second_scope.session_key_hash == third_scope.session_key_hash
    assert len(second_response.headers.get("set-cookie", "")) == 0


def test_malformed_cookie_is_rotated_without_reusing_the_value() -> None:
    settings = Settings()
    response = Response()

    scope = resolve_profile_scope(_request(f"{settings.profile_cookie_name}=too-short"), response, settings)

    assert scope.session_key_hash != "too-short"
    assert settings.profile_cookie_name in response.headers["set-cookie"]
