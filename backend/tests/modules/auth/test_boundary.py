from __future__ import annotations

from pathlib import Path


def test_auth_module_does_not_depend_on_transport_or_orm() -> None:
    root = Path(__file__).parents[3] / "src" / "andromeda" / "modules" / "auth"
    forbidden = ("andromeda.api", "andromeda.infrastructure", "sqlalchemy", "bmstu_parser")
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path
