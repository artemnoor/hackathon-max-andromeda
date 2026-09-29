from __future__ import annotations

from pathlib import Path

from andromeda.ingestion.contracts.normalized import CanonicalSnapshot
from andromeda.ingestion.contracts.raw import RawTracerBundle
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def test_bmstu_fixture_is_emitted_as_raw_and_canonical_contracts() -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()

    assert isinstance(raw, RawTracerBundle)
    assert isinstance(canonical, CanonicalSnapshot)
    assert raw.admission_benefit_records == ()
    assert canonical.admission_benefits is None
    assert {program.education_year for program in raw.programs} == {2026}
    assert {program.code for program in canonical.programs} == {"09.03.01-02", "09.03.01-12"}
    assert all(item.source_name for curriculum in canonical.curricula for item in curriculum.items)
    assert all(source.content_sha256 for source in canonical.sources)
    assert len(canonical.disciplines) == 101
    assert all(discipline.area_weights for discipline in canonical.disciplines)
    assert all(sum(weight.weight for weight in discipline.area_weights) == 1 for discipline in canonical.disciplines)
    assert len(raw.campus_points) == len(canonical.campus_points) == 5
    assert {point.id for point in canonical.campus_points} >= {
        "venue:bmstu:main-campus",
        "venue:bmstu:lab-iu7",
        "venue:bmstu:main-entrance",
    }
