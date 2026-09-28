from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import jevcal_calibrate, jevcal_export


def test_committed_calibration_lock_is_reproducible() -> None:
    jevcal_calibrate._validate_lock(jevcal_calibrate.LOCK_PATH)
    lock = json.loads(jevcal_calibrate.LOCK_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(jevcal_calibrate.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert lock["jevcal_version"] == "0.1.0"
    assert manifest["status"] == "fixture_only"
    assert all(
        value["status"] == "no_threshold" for value in lock["questions"].values()
    )
    from jevcal.runtime import Cascade

    cascade = Cascade(lock, provider=object())
    assert set(cascade.questions) == set(lock["questions"])


def test_calibration_generation_rejects_missing_heldout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    corpus_rows = [
        json.loads(line)
        for line in jevcal_calibrate.CORPUS_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    intent_cases = [row for row in corpus_rows if row["definition_id"] == "intent.v1"]
    observations = tmp_path / "observations.jsonl"
    observations.write_text(
        "".join(
            json.dumps(
                {
                    "case_id": row["case_id"],
                    "definition_id": "intent.v1",
                    "split": "train",
                    "probability": 0.9,
                    "correct": True,
                }
            )
            + "\n"
            for row in intent_cases
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(jevcal_calibrate, "OBSERVATIONS_PATH", observations)

    with pytest.raises(
        jevcal_calibrate.CalibrationArtifactError, match="heldout observations"
    ):
        jevcal_calibrate._build_lock(
            source_kind="fixture",
            corpus_path=jevcal_calibrate.CORPUS_PATH,
            observations_path=observations,
        )


def test_jevcal_can_compile_a_separate_admission_registry_definition(
    tmp_path: Path,
) -> None:
    registry_path = (
        jevcal_calibrate.ROOT
        / "config"
        / "jev"
        / "question-definitions.admission.v1.yaml"
    )
    definition_id = "olympiad-profile-resolution.v1"
    candidates = [
        {"candidate_id": "profile:a", "label": "Olympiad — Algebra"},
        {"candidate_id": "profile:b", "label": "Olympiad — Physics"},
    ]
    cases = [
        {
            "case_id": "admission-fixture-train",
            "definition_id": definition_id,
            "definition_version": "olympiad-profile-resolution-definition.v1",
            "split": "train",
            "input": {"text": "algebra", "candidates": candidates},
            "expected": {"candidate_id": "profile:a"},
        },
        {
            "case_id": "admission-fixture-heldout",
            "definition_id": definition_id,
            "definition_version": "olympiad-profile-resolution-definition.v1",
            "split": "heldout",
            "input": {"text": "physics", "candidates": candidates},
            "expected": {"candidate_id": "profile:b"},
        },
    ]
    corpus_path = tmp_path / "admission-cases.jsonl"
    observations_path = tmp_path / "admission-observations.jsonl"
    corpus_path.write_text(
        "".join(json.dumps(row) + "\n" for row in cases), encoding="utf-8"
    )
    observations_path.write_text(
        "".join(
            json.dumps(
                {
                    "case_id": row["case_id"],
                    "definition_id": definition_id,
                    "split": row["split"],
                    "probability": 0.9,
                    "correct": True,
                }
            )
            + "\n"
            for row in cases
        ),
        encoding="utf-8",
    )

    lock, _ = jevcal_calibrate._build_lock(
        min_support=1,
        source_kind="fixture",
        corpus_path=corpus_path,
        observations_path=observations_path,
        registry_path=registry_path,
        definition_ids=(definition_id,),
    )

    assert set(lock["questions"]) == {definition_id}


def test_production_calibration_requires_full_multiclass_probabilities() -> None:
    with pytest.raises(
        jevcal_calibrate.CalibrationArtifactError, match="full upstream probability"
    ):
        jevcal_calibrate._probability_distribution(
            {
                "case_id": "live-001",
                "probabilities": {"ask_clarification": 0.8, "execute_query": 0.2},
            },
            (
                "ask_clarification",
                "execute_query",
                "compare",
                "show_result",
                "build_report",
                "open_mini_app",
            ),
        )


def test_observation_hash_is_independent_of_windows_line_endings(
    tmp_path: Path,
) -> None:
    lf = tmp_path / "observations-lf.jsonl"
    crlf = tmp_path / "observations-crlf.jsonl"
    lf.write_bytes(b'{"case_id":"one"}\n{"case_id":"two"}\n')
    crlf.write_bytes(b'{"case_id":"one"}\r\n{"case_id":"two"}\r\n')

    assert jevcal_calibrate._hash_file(lf) == jevcal_calibrate._hash_file(crlf)


def test_export_hash_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "one.jsonl"
    second = tmp_path / "two.jsonl"
    assert jevcal_export.main(["--output", str(first)]) == 0
    assert jevcal_export.main(["--output", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    first_meta = json.loads(
        first.with_suffix(".jsonl.meta.json").read_text(encoding="utf-8")
    )
    second_meta = json.loads(
        second.with_suffix(".jsonl.meta.json").read_text(encoding="utf-8")
    )
    assert first_meta["dataset_hash"] == second_meta["dataset_hash"]
