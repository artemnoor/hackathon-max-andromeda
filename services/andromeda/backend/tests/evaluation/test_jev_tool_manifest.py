from __future__ import annotations

import pytest

from scripts import verify_jev_tools


def test_manifest_contains_all_upstream_tools() -> None:
    manifest = verify_jev_tools._load_manifest()
    assert set(manifest["tools"]) == {
        "jevcal",
        "jev-align",
        "system-one-adapter",
        "typesafe-sdk",
        "jevql",
        "jev-tree",
    }
    assert all(tool["canonical_import_allowed"] is False for tool in manifest["tools"].values())


def test_manifest_verifier_accepts_expected_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_jev_tools, "_git", lambda *args: {
        ("branch", "--show-current"): verify_jev_tools.EXPECTED_BRANCH,
        ("rev-parse", "HEAD"): "current-remediation-commit",
    }[args])
    verify_jev_tools.verify()


def test_manifest_verifier_can_enforce_explicit_head(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_jev_tools, "_git", lambda *args: {
        ("branch", "--show-current"): verify_jev_tools.EXPECTED_BRANCH,
        ("rev-parse", "HEAD"): "current-remediation-commit",
    }[args])

    verify_jev_tools.verify(expected_head="current-remediation-commit")

    with pytest.raises(verify_jev_tools.ToolManifestError, match="HEAD drift"):
        verify_jev_tools.verify(expected_head="another-commit")


def test_manifest_verifier_rejects_branch_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_jev_tools, "_git", lambda *args: "other-branch")
    with pytest.raises(verify_jev_tools.ToolManifestError, match="branch drift"):
        verify_jev_tools.verify()
