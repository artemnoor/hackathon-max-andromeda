from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app


def test_api_responses_include_security_headers_and_scope_hsts_to_https(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'security-headers.db').as_posix()}"
    app = create_app(database_url)
    expected_headers = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin-when-cross-origin",
        "permissions-policy": "camera=(), microphone=(), geolocation=()",
        "content-security-policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    }

    with TestClient(app, base_url="http://testserver") as http_client:
        http_response = http_client.get("/openapi.json")
        for header, value in expected_headers.items():
            assert http_response.headers[header] == value
        assert "strict-transport-security" not in http_response.headers

    with TestClient(app, base_url="https://testserver") as https_client:
        https_response = https_client.get("/openapi.json")
        assert https_response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
