from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import run_andromeda_bmstu  # noqa: E402
import run_andromeda_demo  # noqa: E402
import run_tracer_bullet  # noqa: E402
import run_tracer_demo  # noqa: E402


def test_tracer_bullet_wrapper_exports_the_canonical_runner() -> None:
    assert run_tracer_bullet.TracerRunResult is run_andromeda_bmstu.AndromedaRunResult
    assert run_tracer_bullet.run_ingest is run_andromeda_bmstu.run_ingest
    assert run_tracer_bullet.result_payload is run_andromeda_bmstu.result_payload
    assert run_tracer_bullet.selected_program_codes is run_andromeda_bmstu.selected_program_codes


def test_tracer_demo_wrapper_preserves_the_documented_cli_surface() -> None:
    canonical = run_andromeda_demo.build_parser().parse_args(["--mode", "fixture", "--check"])
    compatibility = run_tracer_demo.build_parser().parse_args(["--mode", "fixture", "--check"])
    assert vars(compatibility) == vars(canonical)
    assert callable(run_tracer_demo.run_demo)


def test_canonical_runtime_paths_do_not_import_legacy_runner_names() -> None:
    backend_root = Path(__file__).parents[2]
    canonical_paths = (
        backend_root / "scripts" / "run_andromeda_bmstu.py",
        backend_root / "scripts" / "run_andromeda_demo.py",
        backend_root / "scripts" / "run_andromeda_ingestion.py",
    )
    for path in canonical_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not any(name in {"run_tracer_bullet", "run_tracer_demo"} for name in imports)

    assert "tracer.db" not in (backend_root / "Dockerfile").read_text(encoding="utf-8")
    assert "tracer.db" not in (backend_root / "docker-entrypoint.sh").read_text(encoding="utf-8")
