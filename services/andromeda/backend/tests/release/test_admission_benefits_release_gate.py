from __future__ import annotations

import json
from pathlib import Path

from andromeda.api.main import create_app

BACKEND_ROOT = Path(__file__).parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent
FIXTURE_ROOT = BACKEND_ROOT / "tests" / "fixtures" / "bmstu_admission_benefits"


def test_admission_benefits_release_gate_has_migration_fixtures_and_public_routes() -> None:
    migration = BACKEND_ROOT / "alembic" / "versions" / "0034_admission_benefits.py"
    assert 'revision = "0034_admission_benefits"' in migration.read_text(encoding="utf-8")

    manifest = json.loads((FIXTURE_ROOT / "manifest-2026.json").read_text(encoding="utf-8"))
    assert manifest["admission_year"] == 2026
    assert len(manifest["verification_cases"]) >= 10
    assert {"appendix-5-3.rows.json", "appendix-6.rows.json"}.issubset(
        {document["extract_file"] for document in manifest["documents"]}
    )

    paths = set(create_app("sqlite:///").openapi()["paths"])
    assert "/universities/{university_id}/admission-benefits" in paths
    assert "/programs/{program_id}/admission-benefits" in paths
    assert "/admission-benefits/olympiads/{olympiad_id}/programs" in paths
    assert "/programs/{program_id}/admission-eligibility" in paths


def test_admission_benefits_documentation_keeps_source_trust_boundary_explicit() -> None:
    user_doc = (REPOSITORY_ROOT / "docs" / "admission-benefits.md").read_text(encoding="utf-8")
    architecture_doc = (REPOSITORY_ROOT / "docs" / "architecture" / "admission-benefits.md").read_text(encoding="utf-8")
    assert "Исторические" in user_doc
    assert "Приложение 5.3" in user_doc
    assert "Приложение 6" in user_doc
    assert "Jev" in architecture_doc
    assert "deterministic" in architecture_doc
