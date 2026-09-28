# Dead public surfaces migration note

Date: 2026-09-18

MVP-013 resolved the source-only consumer inventory for the repository and
comparison ports. The removal is intentionally local to the typed boundary;
the modular contexts, reader/writer split, and identity-resolution service stay
in place.

| Removed surface | Evidence | Replacement / retained boundary |
| --- | --- | --- |
| `ComparisonSummaryServicePort` | No production consumer; API owns the concrete `ComparisonSummaryService` application service. | `ComparisonService` remains the real collaborator port used by `ComparisonSummaryService`. |
| `CurriculumRepository` | No source consumer; all consumers use `CurriculumReader`, and infrastructure writes through `CurriculumWriter`. | `CurriculumReader` + `CurriculumWriter`. |
| `ProgramRepository` | No source consumer; application modules use `ProgramReader`, and ingestion uses `ProgramWriter`. | `ProgramReader` + `ProgramWriter`. |
| `DisciplineRepository` | No source consumer; readers and ingestion writers are already separated. | `DisciplineReader` + `DisciplineWriter`. |
| `DisciplineIdentityResolver` | No source consumer; the live behavior is tested in `DisciplineIdentityResolverService` and its typed `IdentityResolution` contract. | Keep identity normalization as a domain service; do not model it as a storage port until a real adapter consumer exists. |

The following are deliberately not removed: `proftest` ranking, matching, and
explanation compatibility facades. They remain bounded import adapters for one
migration cycle, owned by recommendations, and are listed in
`andromeda.composition.compatibility.PROFTEST_COMPATIBILITY_SURFACES` with
explicit removal conditions.

Validation evidence:

- `backend/tests/architecture/test_public_surface_usage.py` proves that the
  removed names have no runtime source definition/reference and that remaining
  public surfaces have an explicit decision.
- `backend/tests/infrastructure/test_identity_resolution.py` preserves the
  matched/new/ambiguous identity behavior.
- `backend/tests/modules/comparison/test_summary.py` preserves summary behavior
  through the real `ComparisonService` port.
