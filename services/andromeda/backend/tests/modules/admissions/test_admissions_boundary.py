from pathlib import Path


MODULE_ROOT = Path(__file__).parents[3] / "src" / "andromeda" / "modules" / "admissions"


def test_module_domain_does_not_depend_on_infrastructure_or_parser() -> None:
    forbidden = ("andromeda.infrastructure", "sqlalchemy", "bmstu_parser")
    for path in (MODULE_ROOT / "domain", MODULE_ROOT / "contracts", MODULE_ROOT / "services"):
        for source in path.rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            assert not any(token in text for token in forbidden), source
