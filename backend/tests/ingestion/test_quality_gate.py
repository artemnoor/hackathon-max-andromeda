from __future__ import annotations

from pathlib import Path

from andromeda.ingestion.contracts.raw import RawSourceGap, SourceLocator
from andromeda.ingestion.quality import PreviousProjection, evaluate_quality
from andromeda.ingestion.registry import adapter_spec, create_adapter, supported_universities


def _fixture_snapshot(university: str):
    spec = adapter_spec(university)
    adapter = create_adapter(university)
    try:
        captured = adapter.capture(mode="fixture", fixture_dir=spec.default_fixture_dir)
        return adapter.parse(captured), captured
    finally:
        close = getattr(adapter, "close", None)
        if close is not None:
            close()


def test_registered_fixture_snapshots_are_accepted_with_explicit_degradation() -> None:
    outcomes = {}
    for university in supported_universities():
        (raw, canonical), _captured = _fixture_snapshot(university)
        outcomes[university] = evaluate_quality(raw, canonical)

    assert all(outcome.accepted for outcome in outcomes.values())
    assert all(outcome.status == "degraded" for outcome in outcomes.values())
    assert all(outcome.metrics["policy_version"] == "mvp023.v1" for outcome in outcomes.values())
    assert outcomes["hse"].metrics["source_gap_count"] == 4
    assert outcomes["hse"].metrics["critical_gap_count"] == 0
    assert "parser_diagnostics_present" in outcomes["hse"].degradable_reasons


def test_quality_gate_rejects_suspicious_regression_before_projection() -> None:
    (raw, canonical), _captured = _fixture_snapshot("bmstu")
    previous = PreviousProjection(
        run_id="ingest:previous-good",
        university_id=str(canonical.university.id),
        program_count=100,
        curriculum_item_count=1000,
        source_count=20,
        program_ids=frozenset(str(program.id) for program in canonical.programs),
    )

    outcome = evaluate_quality(raw, canonical, previous=previous, minimum_relative_count=0.25)

    assert outcome.status == "rejected"
    assert not outcome.accepted
    assert "program_count_regression" in outcome.blocking_reasons
    assert "curriculum_item_count_regression" in outcome.blocking_reasons
    assert outcome.previous_good_run_id == previous.run_id


def test_quality_gate_fails_closed_for_program_source_gap() -> None:
    (raw, canonical), _captured = _fixture_snapshot("bmstu")
    canonical_with_gap = canonical.model_copy(
        update={
            "source_gaps": (
                RawSourceGap(
                    id="source-gap:program-parse",
                    entity_type="program",
                    entity_key=str(canonical.programs[0].id),
                    reason="program_detail_parse_failed",
                    source_url=canonical.programs[0].source_url,
                    locator=SourceLocator(source_url=canonical.programs[0].source_url),
                ),
            )
        }
    )

    outcome = evaluate_quality(raw, canonical_with_gap)

    assert outcome.status == "rejected"
    assert outcome.blocking_reasons == ("critical_source_gap",)
