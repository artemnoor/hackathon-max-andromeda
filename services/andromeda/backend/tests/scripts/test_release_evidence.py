from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "scripts"))

import release_evidence  # noqa: E402


def test_worktree_state_is_secret_free_and_distinguishes_tracked_and_untracked(monkeypatch) -> None:
    values = {
        ("status", "--porcelain=v1", "-z"): b" M tracked.py\0?? local.txt\0",
        ("diff", "--binary"): b"tracked diff",
        ("ls-files", "--others", "--exclude-standard", "-z"): b"local.txt\0",
    }

    monkeypatch.setattr(release_evidence, "_git_bytes", lambda *args: values[args])

    state = release_evidence._worktree_state()

    assert state == {
        "clean": False,
        "statusAvailable": True,
        "trackedChangeCount": 1,
        "untrackedPathCount": 1,
        "trackedDiffSha256": hashlib.sha256(b"tracked diff").hexdigest(),
        "untrackedPathManifestSha256": hashlib.sha256(b"local.txt\0").hexdigest(),
    }


def test_worktree_state_becomes_unknown_when_git_state_cannot_be_read(monkeypatch) -> None:
    monkeypatch.setattr(release_evidence, "_git_bytes", lambda *_args: None)

    assert release_evidence._worktree_state() == {
        "clean": None,
        "statusAvailable": False,
    }
