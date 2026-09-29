from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[3]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "andromeda_verification_cli",
    ROOT / "scripts" / "andromeda.py",
)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
verification_cli = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(verification_cli)


def test_production_smoke_isolates_and_cleans_next_dev_outputs(monkeypatch) -> None:
    captured: dict[str, Path] = {}
    project_tsconfig = verification_cli.FRONTEND / "tsconfig.json"
    project_tsconfig_before = project_tsconfig.read_bytes()

    def capture_smoke_command(
        *_args: object,
        env: dict[str, str],
        **_kwargs: object,
    ) -> None:
        name = env["ANDROMEDA_NEXT_DEV_DIST_DIR"]
        assert re.fullmatch(r"\.next-smoke-[a-zA-Z0-9_-]+", name)
        isolated_dir = verification_cli.FRONTEND / name
        assert isolated_dir.is_dir()
        captured["isolated_dir"] = isolated_dir
        tsconfig_name = env["ANDROMEDA_NEXT_DEV_TSCONFIG_PATH"]
        assert re.fullmatch(r"tsconfig-smoke-[a-zA-Z0-9_-]+\.json", tsconfig_name)
        isolated_tsconfig = verification_cli.FRONTEND / tsconfig_name
        assert isolated_tsconfig.is_file()
        assert json.loads(isolated_tsconfig.read_text(encoding="utf-8")) == json.loads(
            project_tsconfig_before
        )
        captured["isolated_tsconfig"] = isolated_tsconfig
        temporary_config = json.loads(isolated_tsconfig.read_text(encoding="utf-8"))
        temporary_config["include"].append(f"{name}/types/**/*.ts")
        isolated_tsconfig.write_text(json.dumps(temporary_config), encoding="utf-8")

    monkeypatch.setattr(verification_cli, "_run", capture_smoke_command)

    verification_cli._production_smoke()

    assert "isolated_dir" in captured
    assert not captured["isolated_dir"].exists()
    assert "isolated_tsconfig" in captured
    assert not captured["isolated_tsconfig"].exists()
    assert project_tsconfig.read_bytes() == project_tsconfig_before
