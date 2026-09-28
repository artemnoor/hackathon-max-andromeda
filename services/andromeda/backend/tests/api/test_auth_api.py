from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import AccountModel, AuthSessionModel


def _client(tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{(tmp_path / 'auth.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return TestClient(create_app(database_url))


def test_register_login_current_and_logout_use_opaque_cookie_session(tmp_path: Path) -> None:
    client = _client(tmp_path)

    unauthenticated = client.get("/auth/session")
    assert unauthenticated.status_code == 200
    assert unauthenticated.json() == {"authenticated": False, "account": None}

    registered = client.post("/auth/register", json={"email": "student@example.com", "password": "a-secure-password"})
    assert registered.status_code == 201, registered.text
    account = registered.json()["account"]
    assert registered.json()["authenticated"] is True
    assert account["email"] == "student@example.com"
    assert client.cookies.get("andromeda_auth_session")
    assert client.cookies.get("andromeda_profile_session")
    assert "password" not in registered.text
    assert "token" not in registered.text.lower()

    current = client.get("/auth/session")
    assert current.status_code == 200
    assert current.json()["account"]["accountId"] == account["accountId"]

    logged_out = client.post("/auth/logout")
    assert logged_out.status_code == 200
    assert logged_out.json() == {"authenticated": False, "account": None}
    assert client.get("/auth/session").json() == {"authenticated": False, "account": None}

    logged_in = client.post("/auth/login", json={"email": "STUDENT@example.com", "password": "a-secure-password"})
    assert logged_in.status_code == 200, logged_in.text
    assert logged_in.json()["account"]["accountId"] == account["accountId"]
    client.close()


def test_login_error_is_generic_and_duplicate_registration_is_conflict(tmp_path: Path) -> None:
    client = _client(tmp_path)
    rejected_origin = client.post(
        "/auth/register",
        json={"email": "blocked@example.com", "password": "a-secure-password"},
        headers={"Origin": "https://untrusted.example"},
    )
    assert rejected_origin.status_code == 400
    trusted_origin = client.post(
        "/auth/register",
        json={"email": "student@example.com", "password": "a-secure-password"},
        headers={"Origin": "http://127.0.0.1:3000"},
    )
    assert trusted_origin.status_code == 201, trusted_origin.text

    wrong_password = client.post("/auth/login", json={"email": "student@example.com", "password": "wrong-password"})
    unknown_email = client.post("/auth/login", json={"email": "unknown@example.com", "password": "wrong-password"})
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["message"] == "Invalid email or password"

    duplicate = client.post("/auth/register", json={"email": "STUDENT@example.com", "password": "another-password"})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "CONFLICT"
    client.close()


def test_database_stores_only_password_and_session_hashes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/auth/register", json={"email": "student@example.com", "password": "a-secure-password"})
    engine = client.app.state.engine
    with Session(engine) as db_session:
        account = db_session.scalar(select(AccountModel))
        session = db_session.scalar(select(AuthSessionModel))
        assert account is not None
        assert account.password_hash.startswith("$argon2id$")
        assert account.password_hash != "a-secure-password"
        assert session is not None
        assert len(session.token_hash) == 64
        assert session.token_hash != client.cookies.get("andromeda_auth_session")
    client.close()


def test_expired_auth_session_is_unauthenticated_and_cookie_is_cleared(tmp_path: Path) -> None:
    client = _client(tmp_path)
    registered = client.post("/auth/register", json={"email": "expired@example.com", "password": "a-secure-password"})
    assert registered.status_code == 201
    token = client.cookies.get("andromeda_auth_session")
    assert token is not None

    with Session(client.app.state.engine) as db_session:
        session = db_session.scalar(select(AuthSessionModel).where(AuthSessionModel.token_hash.is_not(None)))
        assert session is not None
        session.created_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()

    response = client.get("/auth/session")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "account": None}
    assert "andromeda_auth_session=" in response.headers.get("set-cookie", "")
    client.close()


def test_logout_revokes_one_session_without_invalidating_a_concurrent_session(tmp_path: Path) -> None:
    first = _client(tmp_path)
    registered = first.post("/auth/register", json={"email": "sessions@example.com", "password": "a-secure-password"})
    assert registered.status_code == 201
    account_id = registered.json()["account"]["accountId"]

    second = _client(tmp_path)
    logged_in = second.post("/auth/login", json={"email": "sessions@example.com", "password": "a-secure-password"})
    assert logged_in.status_code == 200
    assert logged_in.json()["account"]["accountId"] == account_id
    first_token = first.cookies.get("andromeda_auth_session")
    second_token = second.cookies.get("andromeda_auth_session")
    assert first_token and second_token and first_token != second_token

    assert first.post("/auth/logout").status_code == 200
    assert first.get("/auth/session").json() == {"authenticated": False, "account": None}
    assert second.get("/auth/session").json()["authenticated"] is True
    first.close()
    second.close()
