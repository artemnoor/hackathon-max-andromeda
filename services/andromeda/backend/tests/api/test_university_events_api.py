from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


OPS_KEY = "test-university-events-ops-key"
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def _seed(tmp_path: Path) -> tuple[str, object]:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'university-events-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    engine.dispose()
    return database_url, canonical


def test_editorial_event_draft_publish_agenda_and_public_projection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url, _ = _seed(tmp_path)
    client = TestClient(create_app(database_url))
    registration = client.post("/auth/register", json={"email": "event-owner@example.com", "password": "a-secure-password"})
    assert registration.status_code == 201, registration.text
    account_id = registration.json()["account"]["accountId"]
    provision = client.post(
        "/ops/university-admin/members",
        headers={"X-Andromeda-Ops-Key": OPS_KEY},
        json={"accountId": account_id, "universityId": "university:bmstu", "role": "owner"},
    )
    assert provision.status_code == 201, provision.text

    body = {
        "slug": "open-day-2026",
        "title": "День открытых дверей",
        "kind": "open_day",
        "format": "hybrid",
        "startsAt": "2026-10-01T10:00:00+03:00",
        "endsAt": "2026-10-01T14:00:00+03:00",
        "description": "План дня",
        "audienceMode": "all_university",
        "agenda": [
            {
                "itemId": "registration",
                "position": 1,
                "title": "Регистрация",
                "startsAt": "2026-10-01T10:00:00+03:00",
                "endsAt": "2026-10-01T10:30:00+03:00",
                "speakerLabel": "Приёмная комиссия",
            },
            {"itemId": "tour", "position": 2, "title": "Экскурсия"},
        ],
    }
    created = client.post("/university-admin/universities/university:bmstu/events", json=body)
    assert created.status_code == 201, created.text
    event = created.json()["event"]
    assert event["status"] == "draft"
    assert len(event["agenda"]) == 2
    assert event["origin"] == "university_editorial"

    public_draft = client.get("/universities/university:bmstu/events")
    assert public_draft.status_code == 200
    assert public_draft.json()["items"] == []

    published = client.post(
        f"/university-admin/universities/university:bmstu/events/{event['eventId']}/publish",
        params={"expectedRevision": event["revision"]},
    )
    assert published.status_code == 200, published.text
    published_event = published.json()["event"]
    public = client.get("/universities/university:bmstu/events")
    assert public.status_code == 200, public.text
    public_event = public.json()["items"][0]
    assert public_event["eventId"] == event["eventId"]
    assert len(public_event["agenda"]) == 2
    assert "revision" not in public_event
    assert "createdByAccountId" not in public_event
    detail = client.get(f"/universities/university:bmstu/events/{event['eventId']}")
    assert detail.status_code == 200, detail.text

    archived = client.delete(
        f"/university-admin/universities/university:bmstu/events/{event['eventId']}",
        params={"expectedRevision": published_event["revision"]},
    )
    assert archived.status_code == 200, archived.text
    assert client.get("/universities/university:bmstu/events").json()["items"] == []


def test_event_json_boundary_and_cross_scope_are_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url, _ = _seed(tmp_path)
    client = TestClient(create_app(database_url))
    registration = client.post("/auth/register", json={"email": "invalid-event-owner@example.com", "password": "a-secure-password"})
    account_id = registration.json()["account"]["accountId"]
    provision = client.post(
        "/ops/university-admin/members",
        headers={"X-Andromeda-Ops-Key": OPS_KEY},
        json={"accountId": account_id, "universityId": "university:bmstu", "role": "owner"},
    )
    assert provision.status_code == 201, provision.text
    invalid = client.post(
        "/university-admin/universities/university:bmstu/events",
        json={
            "slug": "invalid",
            "title": "Invalid",
            "kind": "open_day",
            "format": "offline",
            "startsAt": "2026-10-01T10:00:00",
            "audienceMode": "all_university",
        },
    )
    assert invalid.status_code == 422
    unknown = client.get("/universities/university:hse/events")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "NOT_FOUND"
