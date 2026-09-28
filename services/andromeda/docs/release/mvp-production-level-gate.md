# MVP Production Level release gate

**Current decision:** `PROMOTED — MVP Production Level`

This is the current release gate and its evidence-backed product claim. The
promotion applies to the bounded BMSTU/HSE MVP scope documented in the
[release evidence](mvp-production-level-evidence.md); `UNKNOWN` is never
treated as pass.

## Evidence required

| # | Exit criterion | Current status | Required evidence / command |
|---:|---|---|---|
| 1 | Five primary user flows work end-to-end | `PASS` | `python scripts/andromeda.py production-smoke`, clean deployment smoke, and 52-test Chromium/mobile browser suite |
| 2 | No implemented capability is represented by a placeholder | `PASS` | current capability matrix, UI wording tests, explicit out-of-scope claims |
| 3 | BMSTU/HSE ingestion is reproducible | `PASS` | [source-health run 35437889399](https://github.com/artemnoor/andromeda/actions/runs/35437889399) on `b15dbe7`; BMSTU/HSE completed with typed degraded gaps and zero blocking gaps |
| 4 | Failure, retry, recovery, and last-good state are diagnosable | `PASS` | ingestion recovery/admin-ops tests and run-ID diagnostics |
| 5 | PostgreSQL schema, migrations, and readiness are stable | `PASS` | PostgreSQL 16 clean deployment, readiness head `0022_ingestion_concurrency`, migration suite, restore, and reversible `0022 → 0021 → 0022` check |
| 6 | Critical rules have meaningful tests | `PASS` | [critical test matrix](../test-matrix.md), backend/frontend suites |
| 7 | Full CI passes from clean checkout | `PASS` | [andromeda-ci run 35437883636](https://github.com/artemnoor/andromeda/actions/runs/35437883636) on clean `b15dbe7`; backend/frontend/integration/packaging/documentation/dependency jobs passed |
| 8 | Production-like deployment is runnable | `PASS` | Clean `b15dbe7` images, compose PostgreSQL/backend/frontend, Caddy TLS gateway, readiness, fixture ingestion, full browser flow, and VM/systemd packaging contract |
| 9 | Frontend loading/error/empty/stale/partial states are honest | `PASS` | `frontend-next/tests/mvp-production-flow.spec.ts`, state and responsive suites |
| 10 | Recommendation explains evidence, uncertainty, and provenance | `PASS` | recommendation evidence/explanation tests and browser rendering |
| 11 | Missing data is typed and actionable | `PASS` | source-gap/provenance contracts and partial-data browser assertions |
| 12 | Security baseline passes | `PASS` | Security/request-control/auth/SSRF/PDF/admin tests, dependency audit, and production-like origin/cookie smoke |
| 13 | Documentation matches code and operations | `PASS` | `python scripts/check_docs.py`, current docs and deployment contract gate |
| 14 | Critical paths have no unowned tracer shortcut | `PASS` | architecture/dead-surface checks and tracer migration disposition |
| 15 | Production smoke passes after clean deploy and restore | `PASS` | Clean `b15dbe7` deployment, HTTPS/TLS smoke, fixture projection, backup/isolated restore, and reversible migration rollback |
| 16 | New university onboarding remains adapter/data scoped | `PASS` | adapter contracts, generic-core architecture tests, BMSTU/HSE coexistence |

## Latest live-source evidence

The owner-attached [source-health run 35437889399](https://github.com/artemnoor/andromeda/actions/runs/35437889399)
ran against a disposable, migrated PostgreSQL database on clean checkpoint
`b15dbe7`. Its artifact explicitly reported
`mutatesCanonicalProjection: false`:

| University | Source snapshots | Canonical programmes | Curriculum coverage | Admission coverage | Taxonomy coverage | Source gaps | Blocking gaps | Quality decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| BMSTU | 344 | 134 | 100% | 100% | 100% | 2,817 | 0 | `degraded` |
| HSE | 1,493 | 96 | 88.54% | 51.04% | 84.59% | 122 | 0 | `degraded` |

The full secret-free deployment record, image IDs, browser result, restore
result, and known boundaries are in
[mvp-production-level-evidence.md](mvp-production-level-evidence.md).

## Reproducible metadata

Generate a secret-free JSON metadata artifact for a candidate release:

```powershell
python scripts/release_evidence.py
```

The output is written under `artifacts/release/` and is intentionally not a
promotion switch. It records the commit, lockfile hashes, regression corpus
hashes, an explicit secret-free worktree state, and the 16 checklist items.
For a candidate release checkpoint, require a clean checkout:

```powershell
python scripts/release_evidence.py --require-clean
```

CI/deployment owners attach their run IDs,
image digests, migration head, backup/restore result, and safe logs to the
corresponding rows.

## Rollback references

Keep all of the following with the release record:

- previous backend/frontend image tags or digests;
- previous extracted VM release and the exact standalone `server.js` path;
- applied Alembic revision and compatibility boundary;
- encrypted PostgreSQL backup and isolated restore result;
- fixture/source manifest hashes and current taxonomy/policy versions.

Rows 7, 8, and 15 now have attached clean-checkpoint artifacts. The public
status is `MVP Production Level` for the bounded scope above; it must not be
expanded to unsupported universities or out-of-scope capabilities without a
new evidence cycle.
