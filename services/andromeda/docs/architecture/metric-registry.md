# Metric registry and workload basis

Metric names are allow-listed by `MetricRegistry`; external text is never
turned into a column name or SQL fragment. The registry describes code, label,
unit, domain, supported entities, allowed aggregations, preferred/fallback
basis and semantic version.

The first registry includes semantic shares (`math_share`,
`programming_share`, `ai_share`, `physics_share`, `business_share`,
`analytics_share`), workload (`total_hours`, `total_credits`), assessment,
admission (`passing_score`, `tuition`, `budget_places`) and timeline/activity
signals.

Every metric value carries:

```text
value · unit · basis · coverage · confidence · status
provenance · source gaps
```

`MetricBasis` is explicit (`hours`, `credits`, `course_count` or
`normalized_workload`). A metric policy chooses the preferred comparable basis
and falls back only when coverage rules allow it. No-data is not converted to
zero. Cross-university comparisons therefore expose partial or insufficient
quality instead of presenting a false precision.
