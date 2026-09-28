# Semantic taxonomy

The existing `DisciplineAreaCode`/`DisciplineAreaWeight` distribution is not
replaced. It answers “which academic areas make up this discipline?” and its
weights may sum to one.

The semantic taxonomy answers “how strongly is this signal present?” Values are
independent and do not need to sum to one. The first version contains:

```text
mathematics, statistics, programming, computer_science, data, ai_ml,
physics, engineering, business, management, economics, finance, linguistics,
design, research, analytics, theory, practice, project_work, communication
```

Each `SemanticFeature` has a stable code, description, feature group, value
type and semantic version. Classification values contain confidence, method,
classifier/taxonomy versions, source hash, run ID, evidence and provenance.
Supported methods include `manual`, `rule`, `dictionary`, `model`, `jev`,
`llm` and `inherited`; only the deterministic rule implementation is enabled
by default.

Defaults live in `discipline_semantic_features`. Context-specific values live
in `curriculum_item_semantic_features`. This prevents a same-named discipline
from silently acquiring identical meaning across universities.

The enrichment lifecycle is separate from canonical ingestion. A failed
semantic run does not roll back canonical data and remains retryable. The
current lifecycle records affected and changed item IDs so projections can be
rebuilt incrementally.
