from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.ingestion.universities.bmstu.normalizers.campus import normalize_campus_points
from andromeda.ingestion.universities.bmstu.parser.campus import load_campus_fixture, parse_campus_points
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.errors import ContractError


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "campus" / "raw"
TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def _load_fixture_points() -> list[dict[str, object]]:
    return json.loads((FIXTURE_DIR / "points.json").read_text(encoding="utf-8"))["points"]


def _temporary_source(tmp_path: Path, points: list[dict[str, object]], *, digest: str | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"points": points}, ensure_ascii=False, indent=2).encode("utf-8")
    body_path = tmp_path / "points.json"
    body_path.write_bytes(body)
    manifest = {
        "snapshots": [
            {
                "source_kind": SourceKind.BMSTU_CAMPUS_POINTS.value,
                "requested_url": "https://bmstu.ru/campus/points",
                "final_url": "https://bmstu.ru/campus/points",
                "status_code": 200,
                "content_type": "application/json",
                "captured_at": "2026-09-12T08:00:00+00:00",
                "content_sha256": digest or sha256(body).hexdigest(),
                "body_path": body_path.name,
            }
        ]
    }
    (tmp_path / "source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return load_campus_fixture(tmp_path)


def test_campus_fixture_is_hash_checked_and_contains_physical_point_categories() -> None:
    snapshot = load_campus_fixture(FIXTURE_DIR)
    records = parse_campus_points(snapshot)
    assert snapshot.source_kind == SourceKind.BMSTU_CAMPUS_POINTS.value
    assert snapshot.content_sha256 == sha256(snapshot.body).hexdigest()
    assert len(records) == 5
    assert {record.point_type for record in records} == {"building", "room_zone", "event_venue", "entrance", "other"}
    assert any(record.latitude is None and record.longitude is None for record in records)


def test_campus_normalization_reuses_event_venue_ids_and_canonical_links() -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=TRACER_FIXTURE_DIR, campus_fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()
    assert len(raw.campus_points) == len(canonical.campus_points) == 5
    assert canonical.campus_points[0].id == "venue:bmstu:main-campus"
    assert canonical.campus_points[0].program_ids == ("program:bmstu:09.03.01-02", "program:bmstu:09.03.01-12")
    assert canonical.campus_points[0].department_ids == ("department:bmstu:iu7",)
    assert canonical.campus_points[0].provenance[0].kind is SourceKind.BMSTU_CAMPUS_POINTS


def test_campus_normalization_scopes_program_links_without_dropping_physical_points() -> None:
    adapter = BmstuUniversityAdapter()
    try:
        _, canonical = adapter.parse_sources(
            fixture_dir=TRACER_FIXTURE_DIR,
            campus_fixture_dir=FIXTURE_DIR,
            program_codes=("09.03.01-02",),
        )
    finally:
        adapter.close()
    main = next(point for point in canonical.campus_points if point.id == "venue:bmstu:main-campus")
    innovation = next(point for point in canonical.campus_points if point.id == "venue:bmstu:innovation-hub")
    assert main.program_ids == ("program:bmstu:09.03.01-02",)
    assert innovation.program_ids == ()


def test_campus_parser_fails_closed_for_hash_duplicates_type_and_coordinates(tmp_path: Path) -> None:
    points = _load_fixture_points()
    with pytest.raises(ContractError, match="hash"):
        _temporary_source(tmp_path / "hash", points, digest="0" * 64)

    duplicate = copy.deepcopy(points)
    duplicate.append(copy.deepcopy(duplicate[0]))
    duplicate_dir = tmp_path / "duplicate"
    with pytest.raises(ContractError, match="duplicate campus point external key"):
        parse_campus_points(_temporary_source(duplicate_dir, duplicate))

    unknown_type = copy.deepcopy(points)
    unknown_type[0]["point_type"] = "scene_marker"
    with pytest.raises(ContractError, match="unknown campus point type"):
        parse_campus_points(_temporary_source(tmp_path / "type", unknown_type))

    invalid_coordinates = copy.deepcopy(points)
    invalid_coordinates[0]["latitude"] = "91"
    with pytest.raises(ContractError, match="greater than or equal to -90|coordinate"):
        parse_campus_points(_temporary_source(tmp_path / "coordinates", invalid_coordinates))
