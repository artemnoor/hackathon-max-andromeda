# Ingestion adapter contracts

Status: current MVP implementation, 2026-09-26.

The ingestion boundary remains university-independent at the orchestration and
canonical-contract layers, while source assumptions stay inside the adapter
directories. `SourceAdapter.capture()` returns `CapturedSources` and
`SourceAdapter.parse()` returns the typed `RawTracerBundle` plus
`CanonicalSnapshot`. A raw bundle contains immutable snapshots, normalized raw
records, source gaps, and `RawParserDiagnostic` entries; a gap is never encoded
as an empty numeric value or a fabricated source fact.

## Supported adapter profiles

| Profile | Discovery and source kinds | Adapter-owned assumptions | Blocking vs optional |
| --- | --- | --- | --- |
| BMSTU | `bmstu_common`, catalog API/pages, detail API/pages, public study-plan metadata/documents, orders, and fixture-only events/campus | BMSTU API pagination/detail shape, Yandex public-disk metadata, `priem.bmstu.ru` order manifest, PDF study-plan layout, source direction/profile identity | university/catalog/detail/program identity and a selected study plan are blocking; optional plan document, orders, events, and campus loss becomes a typed gap |
| HSE | `hse_common`, programme catalog/detail, learn-plan index/document, admission rules/places/tuition/passing scores, enrollment documents | HSE programme URL normalization, admission passport traversal, work-plan document shape, historical result pages, HSE regional enrollment pages, absent semester semantics | common/catalog/detail and at least one parseable program are blocking; plans/admission/enrollment sources are independently gap-reported |

The generic core does not import either parser. The adapter-specific fetch
policies own official host allowlists; the shared fetch policy only validates
HTTPS, public DNS targets, bounded redirects/retries/body size, and safe log
metadata.

Knowledge-source discovery uses a separate fixed adapter registry in
`andromeda.ingestion.knowledge_source_adapters`; it does not add policy rules
to the university `SourceAdapter` contract. Registered official-page adapters
reuse the existing bounded HTTP fetcher with a static host allowlist plus the
source revision's path allowlist on every redirect. The one-shot
`scripts/discover_knowledge_sources.py` command persists raw captures through
the existing ingestion repository and stages deterministic review-only claims.
It accepts no arbitrary URL, performs no canonical projection, and never runs
database migrations. Current deterministic extraction is bounded to HTML,
plain text, and PDF with explicit page/document budgets.

This is a bounded policy-source observation path, not a news aggregator or
open web crawl. It polls only an enabled approved source-registry revision;
captures and deterministic claims stay review-only. Poll scheduling belongs to
the deployment operator and is not started implicitly by the API. Limits,
approval steps, failure recovery and the read-only legacy provenance inventory
are documented in the [knowledge-policy operations runbook](operations/knowledge-policy-runbook.md).

## Parser result semantics

- `RawSourceSnapshot` records requested/final URL, status, content hash,
  capture time, response class, access mode, and truncation status.
- `CapturedSources.source_gaps` records source failures that happen before a
  parser can build a row. `RawTracerBundle.source_gaps` carries those gaps
  through normalization and projection.
- `RawParserDiagnostic` records parser-stage warnings and ambiguity reasons
  without logging source bodies. Repeated row-level conditions should be
  aggregated by future adapter work rather than emitted as unbounded log spam.
- Academic year is accepted only from source detail/document metadata. HSE
  returns `None` at the parser boundary when it is absent and the adapter emits
  a degradable program gap; BMSTU uses the study-plan metadata when the detail
  payload does not publish the year and emits the same degradable gap when
  neither source has it. The program remains source-backed, but consumers must
  not present the academic year as known.
- HSE curriculum rows preserve `semester=None`; row order is never used to
  infer a semester. Ambiguous programme matching produces a source gap instead
  of selecting the first candidate.
- HSE curriculum identity first uses the official `learn_plans` index that
  linked a work-plan document. A plan linked by several programme indexes is
  projected to each official owner; an unowned or direction-incompatible row
  remains a typed gap and is never guessed.
- Read-only live source-health probes on 2026-09-19 accepted both adapters as
  `degraded`: BMSTU had 1.0 curriculum/admission/taxonomy coverage across 134
  programmes; HSE had 0.885417 curriculum coverage across 96 programmes and
  0.510417 admission coverage. These are operational evidence, not a release
  promotion by themselves.
- Optional source absence is distinguishable from a malformed or failed
  source by the stable gap reason and the presence/absence of a valid snapshot.

## Verification evidence

- `backend/tests/ingestion/test_fetch_security.py`,
  `test_retry_policy.py`, and `test_source_allowlists.py` cover URL/DNS,
  redirect, size, retry, and provenance behavior offline.
- `backend/tests/ingestion/test_bmstu_source_capture.py` and
  `test_hse_parser.py` cover adapter-specific discovery and parser contracts.
- `backend/tests/integration/test_bmstu_full_ingestion.py` and
  `test_hse_full_ingestion.py` prove canonical IDs, source hashes, curriculum,
  admission records, and repeatable projection from fixtures.
- HSE `source_manifest.json` hashes are checked against every fixture body at
  load time; BMSTU has the same invariant.
- Policy-source polling, claim staging, last-good recovery and URL/DNS limits
  are covered by `backend/tests/ingestion/test_knowledge_source_discovery.py`,
  `backend/tests/ingestion/test_fetch_security.py` and their repository/API
  suites. This does not establish broad regulatory-source coverage or a
  production polling schedule; those are owned operationally. See the
  [knowledge-policy runbook](operations/knowledge-policy-runbook.md).
