from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from andromeda.ingestion.universities.bmstu.normalizers.events import normalize_events
from andromeda.ingestion.universities.bmstu.parser.events import load_event_fixture, parse_events
from andromeda.shared.contracts.errors import ContractError
from andromeda.shared.contracts.enums import SourceKind
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "events" / "raw"
TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def _load_fixture_events() -> list[dict[str, object]]:
    return json.loads((FIXTURE_DIR / "events.json").read_text(encoding="utf-8"))["events"]


def _temporary_source(tmp_path: Path, events: list[dict[str, object]], *, digest: str | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"events": events}, ensure_ascii=False, indent=2).encode("utf-8")
    body_path = tmp_path / "events.json"
    body_path.write_bytes(body)
    manifest = {
        "snapshots": [
            {
                "source_kind": SourceKind.BMSTU_EVENTS.value,
                "requested_url": "https://bmstu.ru/events",
                "final_url": "https://bmstu.ru/events",
                "status_code": 200,
                "content_type": "application/json",
                "captured_at": "2026-09-12T08:00:00+00:00",
                "content_sha256": digest or sha256(body).hexdigest(),
                "body_path": body_path.name,
            }
        ]
    }
    (tmp_path / "source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return load_event_fixture(tmp_path)


def test_event_fixture_is_hash_checked_and_provenance_backed() -> None:
    snapshot = load_event_fixture(FIXTURE_DIR)
    records = parse_events(snapshot)
    assert snapshot.source_kind == SourceKind.BMSTU_EVENTS.value
    assert snapshot.content_sha256 == sha256(snapshot.body).hexdigest()
    assert len(records) == 5
    assert all(record.source_url == snapshot.requested_url for record in records)


def test_event_normalization_is_deterministic_and_maps_program_codes() -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=TRACER_FIXTURE_DIR, event_fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()
    assert [event.id for event in canonical.events] == [
        "event:bmstu:dod-2026",
        "event:bmstu:robotics-workshop-2026",
        "event:bmstu:research-day-2026",
        "event:bmstu:online-open-lecture-2026",
        "event:bmstu:career-hybrid-2026",
    ]
    assert set(canonical.events[0].program_ids) == {"program:bmstu:09.03.01-02", "program:bmstu:09.03.01-12"}
    assert canonical.events[0].department_ids == ("department:bmstu:iu7",)
    assert len(raw.events) == len(canonical.events)
    assert all(event.provenance[0].kind is SourceKind.BMSTU_EVENTS for event in canonical.events)


def test_event_normalization_scopes_mixed_program_links_to_selected_program() -> None:
    adapter = BmstuUniversityAdapter()
    try:
        _, canonical = adapter.parse_sources(
            fixture_dir=TRACER_FIXTURE_DIR,
            event_fixture_dir=FIXTURE_DIR,
            program_codes=("09.03.01-02",),
        )
    finally:
        adapter.close()

    mixed = next(event for event in canonical.events if event.id == "event:bmstu:dod-2026")
    assert mixed.program_ids == ("program:bmstu:09.03.01-02",)
    assert {event.id for event in canonical.events} == {
        "event:bmstu:dod-2026",
        "event:bmstu:robotics-workshop-2026",
        "event:bmstu:research-day-2026",
    }


def test_event_fixture_fail_closed_for_hash_duplicate_unknown_link_coordinates_and_required_fields(tmp_path: Path) -> None:
    events = _load_fixture_events()
    with pytest.raises(ContractError, match="hash"):
        _temporary_source(tmp_path / "hash", events, digest="0" * 64)

    duplicate = copy.deepcopy(events)
    duplicate.append(copy.deepcopy(duplicate[0]))
    with pytest.raises(ContractError, match="duplicate event external key"):
        parse_events(_temporary_source(tmp_path / "duplicate", duplicate))

    unknown = copy.deepcopy(events)
    unknown[0]["program_codes"] = ["99.99.99-99"]
    source = _temporary_source(tmp_path / "unknown", unknown)
    records = parse_events(source)
    with pytest.raises(ContractError, match="Unknown BMSTU event program identity"):
        normalize_events(records, programs=(), snapshots=(source,))

    invalid_coordinates = copy.deepcopy(events)
    invalid_coordinates[0]["venue"]["latitude"] = "91"
    with pytest.raises(ContractError, match="greater than or equal to -90|less than or equal to 90|coordinate"):
        parse_events(_temporary_source(tmp_path / "coordinates", invalid_coordinates))

    missing_title = copy.deepcopy(events)
    del missing_title[0]["title"]
    with pytest.raises(ContractError, match="required non-empty text"):
        parse_events(_temporary_source(tmp_path / "missing", missing_title))
