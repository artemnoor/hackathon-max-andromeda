from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database import models as _models
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


OPS_KEY = "test-university-catalog-ops-key"
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def _seed(tmp_path: Path) -> tuple[str, object]:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'university-catalog-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    engine.dispose()
    return database_url, canonical


def test_public_catalog_is_anonymous_and_hides_editorial_overlay_without_touching_canonical_api(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url, canonical = _seed(tmp_path)
    owner = TestClient(create_app(database_url))
    owner_registration = owner.post("/auth/register", json={"email": "catalog-owner@example.com", "password": "a-secure-password"})
    assert owner_registration.status_code == 201, owner_registration.text
    owner_account_id = owner_registration.json()["account"]["accountId"]
    provision = owner.post(
        "/ops/university-admin/members",
        headers={"X-Andromeda-Ops-Key": OPS_KEY},
        json={"accountId": owner_account_id, "universityId": "university:bmstu", "role": "owner"},
    )
    assert provision.status_code == 201, provision.text

    faculty = owner.post(
        "/university-admin/universities/university:bmstu/units",
        json={"unitType": "faculty", "slug": "iu", "name": "Факультет ИУ", "status": "published"},
    )
    assert faculty.status_code == 201, faculty.text
    category = owner.post(
        "/university-admin/universities/university:bmstu/categories",
        json={"slug": "programs", "name": "Программы", "categoryKind": "program", "status": "published"},
    )
    assert category.status_code == 201, category.text
    link_response = owner.put(
        "/university-admin/universities/university:bmstu/catalog-links",
        json={
            "categoryPrograms": [[category.json()["categoryId"], canonical.programs[0].id]],
            "categoryDisciplines": [],
            "unitPrograms": [[faculty.json()["unitId"], canonical.programs[0].id]],
            "unitDisciplines": [],
        },
    )
    assert link_response.status_code == 200, link_response.text

    anonymous = TestClient(create_app(database_url))
    universities = anonymous.get("/universities")
    assert universities.status_code == 200, universities.text
    assert universities.json()["items"][0]["id"] == "university:bmstu"
    public_before = anonymous.get("/universities/university:bmstu/catalog")
    assert public_before.status_code == 200, public_before.text
    assert public_before.json()["units"][0]["name"] == "Факультет ИУ"
    assert len(public_before.json()["programs"]) == len(canonical.programs)
    assert public_before.json()["programs"][0]["categoryIds"] == [category.json()["categoryId"]]

    program_id = canonical.programs[0].id
    hidden = owner.patch(
        f"/university-admin/universities/university:bmstu/programs/{program_id}",
        json={"displayName": "Скрытая программа", "visibility": "hidden"},
    )
    assert hidden.status_code == 200, hidden.text

    public_after = anonymous.get("/universities/university:bmstu/catalog")
    assert public_after.status_code == 200, public_after.text
    assert program_id not in {item["programId"] for item in public_after.json()["programs"]}
    canonical_response = anonymous.get(f"/programs/{program_id}")
    assert canonical_response.status_code == 200, canonical_response.text
    assert canonical_response.json()["program"]["id"] == program_id


def test_catalog_mutations_require_editor_and_unknown_public_scope_is_not_found(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url, _ = _seed(tmp_path)
    client = TestClient(create_app(database_url))
    response = client.post(
        "/university-admin/universities/university:hse/units",
        json={"unitType": "faculty", "slug": "test", "name": "Test", "status": "published"},
    )
    assert response.status_code == 401
    missing = client.get("/universities/university:hse/catalog")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
