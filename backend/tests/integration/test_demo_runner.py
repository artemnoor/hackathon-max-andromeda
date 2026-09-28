from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import run_andromeda_demo  # noqa: E402
from run_andromeda_bmstu import AndromedaRunResult  # noqa: E402


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False

    def poll(self) -> int | None:
        return None if not self.terminated else 0

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


def test_demo_wires_ingest_api_frontend_and_compare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = AndromedaRunResult("run-1", ("program:test-a", "program:test-b"), 2, 4, ("a" * 64, "b" * 64), 5)
    commands: list[tuple[str, ...]] = []
    processes: list[FakeProcess] = []

    monkeypatch.setattr(run_andromeda_demo, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_andromeda_demo, "run_ingest", lambda **_: result)
    monkeypatch.setattr(run_andromeda_demo, "wait_for_http", lambda *args: None)
    monkeypatch.setattr(run_andromeda_demo, "discover_program_codes", lambda *_args: ("test-a", "test-b"))
    monkeypatch.setattr(run_andromeda_demo, "verify_compare", lambda *args: None)
    monkeypatch.setattr(run_andromeda_demo, "verify_admissions", lambda *args: None)
    monkeypatch.setattr(run_andromeda_demo, "verify_events", lambda *args: None)
    monkeypatch.setattr(run_andromeda_demo, "verify_campus_data", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_andromeda_demo, "verify_og", lambda *args: None)

    def fake_start(command: list[str], cwd: Path, env: dict[str, str], label: str) -> FakeProcess:
        commands.append(tuple(command))
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(run_andromeda_demo, "_start_process", fake_start)
    monkeypatch.setattr(run_andromeda_demo, "_stop_process", lambda process, label: process.terminate())

    args = Namespace(
        mode="fixture",
        fixture_dir=tmp_path,
        database_url="sqlite:///backend/data/test.db",
        program_codes=None,
        program_ids=None,
        host="127.0.0.1",
        api_port=8000,
        frontend_port=3000,
        timeout=1.0,
        check=True,
    )

    assert run_andromeda_demo.run_demo(args) == result
    assert commands[0][0:3] == (run_andromeda_demo.sys.executable, "-m", "uvicorn")
    assert commands[1][0:3] == ("npm.cmd" if run_andromeda_demo.os.name == "nt" else "npm", "run", "dev")
    assert all(process.terminated for process in processes)
