from __future__ import annotations

import json
from pathlib import Path

from scripts import evaluate_jev_ecosystem


ROOT = Path(__file__).resolve().parents[2]


def test_offline_harness_report_is_fixture_only_and_safe(tmp_path: Path) -> None:
    output = tmp_path / "jev-report.json"

    assert evaluate_jev_ecosystem.main(["--output", str(output), "--check"]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == "andromeda-jev-ecosystem-report.v1"
    assert report["calibration_status"] == "fixture_only"
    assert report["paths"]["deterministic"]["status"] == "available"
    assert report["paths"]["official_jev"]["status"] == "not_run_offline"


def test_offline_harness_rejects_mixed_registry_hash(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(evaluate_jev_ecosystem, "MANIFEST_PATH", tmp_path / "manifest.json")
    evaluate_jev_ecosystem.MANIFEST_PATH.write_text(
        json.dumps({"status": "fixture_only", "registry_hash": "sha256:wrong"}),
        encoding="utf-8",
    )

    try:
        evaluate_jev_ecosystem.main(["--output", str(tmp_path / "report.json"), "--check"])
    except ValueError as exc:
        assert "registry hash" in str(exc)
    else:
        raise AssertionError("mixed registry hash must fail closed")
