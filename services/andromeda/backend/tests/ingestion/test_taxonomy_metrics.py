import json
from pathlib import Path

from andromeda.ingestion.registry import create_adapter
from andromeda.ingestion.taxonomy_metrics import calculate_taxonomy_metrics
from andromeda.modules.disciplines.domain.areas import DisciplineAreaCode
from andromeda.modules.disciplines.services.classifier import RuleBasedDisciplineClassifier


FIXTURE = Path(__file__).parents[1] / "fixtures" / "taxonomy" / "discipline_classification.json"


def test_taxonomy_regression_corpus_covers_all_22_areas_and_known_unknown() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    classifier = RuleBasedDisciplineClassifier()
    outcomes = tuple(classifier.classify_with_outcome(item["name"]) for item in payload["cases"])

    expected_areas = {
        item["primary_area"]
        for item in payload["cases"]
        if item.get("method") != "unresolved"
    }
    observed_areas = {outcome.area_weights[0].area.value for outcome in outcomes if outcome.method != "unresolved"}

    assert payload["taxonomy_version"] == "taxonomy-22.v1"
    assert expected_areas == {area.value for area in DisciplineAreaCode}
    assert observed_areas >= expected_areas
    assert outcomes[-1].method == "unresolved"


def test_fixture_taxonomy_metrics_are_reproducible_and_unknowns_are_degradable() -> None:
    for university in ("bmstu", "hse"):
        adapter = create_adapter(university)
        try:
            raw, canonical = adapter.parse_sources(mode="fixture")
        finally:
            adapter.close()

        metrics = calculate_taxonomy_metrics(
            canonical,
            source_hashes=tuple(snapshot.content_sha256 for snapshot in raw.snapshots),
            run_id="ingest:taxonomy-metrics",
        )
        repeated = calculate_taxonomy_metrics(
            canonical,
            source_hashes=tuple(snapshot.content_sha256 for snapshot in raw.snapshots),
            run_id="ingest:taxonomy-metrics",
        )

        assert metrics == repeated
        assert metrics.outcome_count == metrics.discipline_count
        assert metrics.source_hashes
        assert metrics.run_id == "ingest:taxonomy-metrics"
        assert 0 <= metrics.classification_coverage <= 1
        assert metrics.unresolved_count >= 0
        assert metrics.area_usage
