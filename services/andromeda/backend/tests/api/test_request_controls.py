from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.api.request_controls import SlidingWindowRateLimiter, normalize_correlation_id


def test_correlation_id_is_bounded_and_request_completion_is_logged(tmp_path: Path, caplog) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'request-controls.db').as_posix()}")
    with caplog.at_level(logging.INFO, logger="andromeda.api.request"):
        response = TestClient(app).get(
            "/health/live",
            headers={"X-Correlation-Id": "a" * 65},
        )

    correlation_id = response.headers["X-Correlation-Id"]
    assert response.status_code == 200
    assert len(correlation_id) == 32
    assert "request_complete method=GET path=/health/live status=200" in caplog.text
    assert f"correlation_id={correlation_id}" in caplog.text


def test_untrusted_origin_is_rejected_for_state_changes(tmp_path: Path) -> None:
    client = TestClient(create_app(f"sqlite:///{(tmp_path / 'csrf.db').as_posix()}"))

    response = client.post(
        "/auth/logout",
        headers={"Origin": "https://untrusted.example"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_auth_rate_limit_returns_safe_contract_and_retry_after(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_AUTH_RATE_LIMIT_MAX", "2")
    client = TestClient(create_app(f"sqlite:///{(tmp_path / 'rate-limit.db').as_posix()}"))
    payload = {"email": "student@example.com", "password": "a-secure-password"}

    first = client.post("/auth/login", json=payload)
    second = client.post("/auth/login", json=payload)
    limited = client.post("/auth/login", json=payload)

    assert first.status_code == 500
    assert second.status_code == 500
    assert limited.status_code == 429
    assert limited.json() == {"code": "RATE_LIMITED", "message": "Too many requests", "details": []}
    assert limited.headers["retry-after"] == "60"


def test_public_v1_and_legacy_auth_routes_share_the_same_rate_limit_bucket(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ANDROMEDA_AUTH_RATE_LIMIT_MAX", "1")
    client = TestClient(create_app(f"sqlite:///{(tmp_path / 'versioned-rate-limit.db').as_posix()}"))
    payload = {"email": "student@example.com", "password": "a-secure-password"}

    first = client.post("/auth/login", json=payload)
    limited = client.post("/api/v1/auth/login", json=payload)

    assert first.status_code == 500
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_unhandled_exception_is_safe_and_correlated(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'exception.db').as_posix()}")

    def boom() -> None:
        raise RuntimeError("secret implementation detail")

    app.add_api_route("/test/boom", boom, methods=["GET"])
    response = TestClient(app, raise_server_exceptions=False).get(
        "/test/boom",
        headers={"X-Correlation-Id": "test-correlation"},
    )

    assert response.status_code == 500
    assert response.json() == {"code": "INTERNAL_ERROR", "message": "Internal server error", "details": []}
    assert response.headers["X-Correlation-Id"] == "test-correlation"
    assert "secret implementation detail" not in response.text


def test_sliding_window_limiter_expires_entries() -> None:
    limiter = SlidingWindowRateLimiter(10)

    assert limiter.allow("client", 2, now=100.0)
    assert limiter.allow("client", 2, now=100.1)
    assert not limiter.allow("client", 2, now=100.2)
    assert limiter.allow("client", 2, now=110.1)


def test_invalid_correlation_id_is_replaced() -> None:
    normalized = normalize_correlation_id("contains spaces")

    assert len(normalized) == 32
