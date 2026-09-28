from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.database.models import UniversityModel


OPS_KEY = "test-university-admin-ops-key"
UNIVERSITY_ID = "university:bmstu"


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, str]:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url = f"sqlite:///{(tmp_path / 'university-admin-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        session.add(
            UniversityModel(
                id=UNIVERSITY_ID,
                name="МГТУ им. Н. Э. Баумана",
                city="Москва",
                official_site="https://bmstu.ru/",
                address="Москва",
            )
        )
        session.commit()
    engine.dispose()
    return TestClient(create_app(database_url)), database_url


def _register(client: TestClient, email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "a-secure-password"})
    assert response.status_code == 201, response.text
    return response.json()["account"]["accountId"]


def test_membership_discovery_requires_session_and_never_accepts_account_id(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)

    anonymous = client.get("/university-admin/memberships", params={"accountId": "account:" + "a" * 32})

    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "UNAUTHORIZED"


def test_ops_bootstraps_owner_and_owner_manages_existing_account(tmp_path: Path, monkeypatch) -> None:
    owner, database_url = _client(tmp_path, monkeypatch)
    target = TestClient(create_app(database_url))
    owner_account_id = _register(owner, "owner@example.com")
    target_account_id = _register(target, "editor@example.com")

    provision = owner.post(
        "/ops/university-admin/members",
        headers={"X-Andromeda-Ops-Key": OPS_KEY},
        json={"accountId": owner_account_id, "universityId": UNIVERSITY_ID, "role": "owner"},
    )
    assert provision.status_code == 201, provision.text
    owner_membership = provision.json()
    assert owner_membership["role"] == "owner"
    assert "email" not in provision.text

    discovered = owner.get("/university-admin/memberships")
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["items"][0]["universityName"] == "МГТУ им. Н. Э. Баумана"

    added = owner.post(
        f"/university-admin/universities/{UNIVERSITY_ID}/members",
        json={"accountId": target_account_id, "role": "editor"},
    )
    assert added.status_code == 201, added.text
    assert added.json()["role"] == "editor"

    members = owner.get(f"/university-admin/universities/{UNIVERSITY_ID}/members")
    assert members.status_code == 200, members.text
    assert {item["accountId"] for item in members.json()["items"]} == {owner_account_id, target_account_id}

    editor_memberships = target.get("/university-admin/memberships")
    assert editor_memberships.status_code == 200, editor_memberships.text
    assert editor_memberships.json()["items"][0]["role"] == "editor"


def test_editor_gets_forbidden_and_unknown_scope_is_not_enumerated(tmp_path: Path, monkeypatch) -> None:
    owner, database_url = _client(tmp_path, monkeypatch)
    target = TestClient(create_app(database_url))
    owner_account_id = _register(owner, "owner@example.com")
    target_account_id = _register(target, "viewer@example.com")
    owner.post(
        "/ops/university-admin/members",
        headers={"X-Andromeda-Ops-Key": OPS_KEY},
        json={"accountId": owner_account_id, "universityId": UNIVERSITY_ID, "role": "owner"},
    )
    added = owner.post(
        f"/university-admin/universities/{UNIVERSITY_ID}/members",
        json={"accountId": target_account_id, "role": "viewer"},
    )
    assert added.status_code == 201

    denied = target.post(
        f"/university-admin/universities/{UNIVERSITY_ID}/members",
        json={"accountId": owner_account_id, "role": "viewer"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"

    unknown_scope = owner.get("/university-admin/universities/university:hse/members")
    assert unknown_scope.status_code == 404
    assert unknown_scope.json()["code"] == "NOT_FOUND"


def test_last_owner_revoke_is_conflict_and_ops_key_does_not_enumerate(tmp_path: Path, monkeypatch) -> None:
    owner, _ = _client(tmp_path, monkeypatch)
    owner_account_id = _register(owner, "owner@example.com")

    missing_key = owner.post(
        "/ops/university-admin/members",
        json={"accountId": owner_account_id, "universityId": UNIVERSITY_ID, "role": "owner"},
    )
    assert missing_key.status_code == 404
    assert missing_key.json()["code"] == "NOT_FOUND"

    provision = owner.post(
        "/ops/university-admin/members",
        headers={"X-Andromeda-Ops-Key": OPS_KEY},
        json={"accountId": owner_account_id, "universityId": UNIVERSITY_ID, "role": "owner"},
    )
    membership = provision.json()
    blocked = owner.delete(
        f"/university-admin/universities/{UNIVERSITY_ID}/members/{membership['membershipId']}",
        params={"expectedRevision": membership["revision"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "CONFLICT"


def test_university_admin_openapi_has_explicit_forbidden_response() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))
    document = client.get("/openapi.json").json()

    assert "/university-admin/memberships" in document["paths"]
    assert "403" in document["paths"]["/university-admin/universities/{university_id}/members"]["post"]["responses"]
