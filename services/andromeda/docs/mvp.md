# Andromeda MVP scope / MVP Production Level

## Stage

MVP Production Level for the bounded, source-backed BMSTU/HSE scope. Core loop:
**Discover → Refine → Shortlist → Compare → Decide**. The evidence and known
boundaries are recorded in [the release record](release/mvp-production-level-evidence.md)
and [the gate](release/mvp-production-level-gate.md).

## Target user

Абитуриент, который выбирает между несколькими образовательными программами.

## Core job

Понять доступные программы, проверить ограничения поступления, сократить варианты до объяснимого shortlist, сравнить финальных кандидатов и сохранить собственное решение.

## MVP includes

- multi-university catalog: BMSTU and HSE через adapter model;
- curricula, disciplines, admissions, Admission Fit и Content Fit;
- anonymous/account persistence для `DecisionContext` и shortlist;
- explicit final choice с optimistic revision;
- source provenance, source gaps и fail-closed ingestion;
- adaptive profile как необязательный refinement-инструмент;
- comparison summary-first и raw evidence drill-down;
- product analytics, admin ingestion audit, events/campus там, где есть source-backed данные;
- Web and future MAX clients as consumers of the same channel-neutral backend API.

## Out of MVP

Career Fit, personal career guidance, ML ranking, validated personal Workload Readiness, отзывы, новости, социальные функции, guaranteed admission predictions, external public sharing и массовое покрытие университетов.

## Definition of Done

1. BMSTU и HSE coexist в PostgreSQL с university-scoped IDs.
2. Пользователь может завершить discover → shortlist → compare → final choice без профтеста.
3. Сохранённый shortlist и final choice переживают reload и account transfer с явным conflict outcome.
4. Missing source data не превращается в ноль и объясняется в UI.
5. Live ingestion публикуется только после capture, parse, validation, identity и sanity checks.
6. OpenAPI, generated frontend client, backend/frontend/fullstack/PostgreSQL/proftest checks зелёные.
