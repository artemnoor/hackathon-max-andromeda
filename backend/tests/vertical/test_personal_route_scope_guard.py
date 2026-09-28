from __future__ import annotations

from pathlib import Path


def test_personal_route_module_stays_free_of_map_and_storage_implementation() -> None:
    module_root = Path(__file__).parents[2] / "src" / "andromeda" / "modules" / "personal_route"
    contents = "\n".join(path.read_text(encoding="utf-8") for path in module_root.rglob("*.py"))
    forbidden_terms = ("sqlalchemy", "fastapi", "mapbox", "leaflet", "cesium", "three.js", "route_optimizer", "directions")

    assert not any(term in contents.casefold() for term in forbidden_terms)
