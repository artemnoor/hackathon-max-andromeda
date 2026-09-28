from __future__ import annotations

from pathlib import Path


def test_campus_slice_does_not_add_map_or_routing_frontend_assets() -> None:
    frontend_root = Path(__file__).parents[2].parent / "frontend"
    forbidden_terms = ("mapbox", "leaflet", "cesium", "three", "route optimizer", "route_optimizer")
    contents = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore").casefold()
        for path in frontend_root.rglob("*")
        if path.is_file()
        and "node_modules" not in path.parts
        and "dist" not in path.parts
        and path.suffix in {".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".html"}
    )
    assert not any(term in contents for term in forbidden_terms)
