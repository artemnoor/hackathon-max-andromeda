from __future__ import annotations

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[3]
LEDGER_PATH = REPOSITORY_ROOT / "docs" / "mvp-production-level.md"
ALLOWED_STATUSES = {
    "`VERIFIED`",
    "`PARTIALLY VERIFIED`",
    "`UNVERIFIED`",
    "`INTENTIONAL` — out of scope",
    "`FUTURE RISK`",
}


def test_mvp_evidence_ledger_links_and_release_markers_are_valid() -> None:
    document = LEDGER_PATH.read_text(encoding="utf-8")

    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document):
        if "://" in target:
            continue
        local_target = target.split("#", 1)[0].split("::", 1)[0]
        assert local_target
        assert (LEDGER_PATH.parent / local_target).resolve().exists(), target

    ledger_section = document.split("## Evidence ledger", 1)[1].split("## Release decision", 1)[0]
    ledger_rows = [line for line in ledger_section.splitlines() if line.startswith("| ")]
    assert ledger_rows
    assert all(row.split("|")[2].strip() in ALLOWED_STATUSES for row in ledger_rows[2:])
    assert "Current release decision:** **PROMOTED — MVP Production Level" in document
    assert "MVP-095" in document
    assert "PostgreSQL" in document
    assert "UNVERIFIED" in document
