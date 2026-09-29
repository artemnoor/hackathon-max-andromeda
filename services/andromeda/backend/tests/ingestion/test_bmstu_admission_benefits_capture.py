from __future__ import annotations

import json
import shutil
from pathlib import Path

from andromeda.ingestion.universities.bmstu.admission_benefits import (
    BmstuAdmissionBenefitsCapture,
)

INDEX_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "bmstu"
    / "admission_benefits"
    / "document-index-2026.json"
)


def _fixture_dir(tmp_path: Path) -> Path:
    fixture_dir = tmp_path / "admission-benefits"
    fixture_dir.mkdir()
    payload = json.loads(INDEX_FIXTURE.read_text(encoding="utf-8"))
    (fixture_dir / "document-index-2026.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    documents = payload["content"]["document-list"][0]["documents"]
    for document in documents:
        if document["id"] in {182, 189, 190, 191, 315, 201, 1088, 192, 193, 194, 307}:
            (fixture_dir / f"document-{document['id']}.pdf").write_bytes(
                b"%PDF-1.7 official fixture " + str(document["id"]).encode()
            )
    for profile in ("engineering", "programming"):
        shutil.copyfile(
            INDEX_FIXTURE.parent / f"shag-{profile}.html.extract.json",
            fixture_dir / f"shag-{profile}.html.extract.json",
        )
    for file_name in ("appendix-5-4-extract.json", "appendix-5-5-extract.json"):
        shutil.copyfile(INDEX_FIXTURE.parent / file_name, fixture_dir / file_name)
    return fixture_dir


def test_fixture_capture_discovers_and_captures_selected_documents_with_stable_hashes(
    tmp_path: Path,
) -> None:
    fixture_dir = _fixture_dir(tmp_path)
    capture = BmstuAdmissionBenefitsCapture()
    try:
        first = capture.capture(mode="fixture", fixture_dir=fixture_dir)
        second = capture.capture(mode="fixture", fixture_dir=fixture_dir)
    finally:
        capture.close()

    assert first.report.discovered == len(first.manifest.selected)
    assert first.report.fetched == first.report.discovered
    assert first.report.failed == 0
    assert first.report.source_hashes == second.report.source_hashes
    assert first.captured.snapshots[0].source_kind == "bmstu_admission_document_index"
    assert {snapshot.source_kind for snapshot in first.captured.snapshots} >= {
        "bmstu_admission_document:appendix_5_3",
        "bmstu_admission_document:appendix_6",
        "bmstu_olympiad_profile:engineering",
        "bmstu_olympiad_profile:programming",
    }


def test_fixture_capture_keeps_partial_failure_as_source_gap(tmp_path: Path) -> None:
    fixture_dir = _fixture_dir(tmp_path)
    (fixture_dir / "document-315.pdf").unlink()

    capture = BmstuAdmissionBenefitsCapture()
    try:
        result = capture.capture(mode="fixture", fixture_dir=fixture_dir)
    finally:
        capture.close()

    assert result.report.failed == 1
    assert any(
        "document_fixture_missing" in gap.reason for gap in result.captured.source_gaps
    )
    assert result.report.fetched == result.report.discovered - 1


def test_changed_fixture_body_creates_new_snapshot_hash(tmp_path: Path) -> None:
    fixture_dir = _fixture_dir(tmp_path)
    capture = BmstuAdmissionBenefitsCapture()
    try:
        first = capture.capture(mode="fixture", fixture_dir=fixture_dir)
        (fixture_dir / "document-315.pdf").write_bytes(
            b"%PDF-1.7 changed official fixture"
        )
        second = capture.capture(mode="fixture", fixture_dir=fixture_dir)
    finally:
        capture.close()

    assert first.report.source_hashes != second.report.source_hashes
