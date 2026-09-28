# Andromeda MVP Production Level release evidence

**Decision:** `PROMOTED — MVP Production Level`

**Evidence date:** 2026-09-19

**Release code checkpoint:** `b15dbe7692ec2f6f2192dc8f34fc12ceafe4af93`

**Scope:** production-capable MVP with source-backed BMSTU/HSE coverage and a
single-instance operational layout. This is not an enterprise platform and it
does not claim Career Fit, validated Workload Readiness, ML ranking, or broad
university coverage.

This record attaches the evidence used to close `MVP-095`. It is intentionally
secret-free: it contains no credentials, database URLs with passwords, raw
source bodies, user profiles, or full ingestion payloads.

## Release evidence

| Area | Evidence | Result |
| --- | --- | --- |
| Clean-checkpoint attribution | `python scripts/release_evidence.py --require-clean` on a detached clean checkout of `b15dbe7`; metadata reported `clean: true`, zero tracked changes, zero untracked paths, and immutable lock/corpus hashes | PASS |
| Full CI | [andromeda-ci run 35437883636](https://github.com/artemnoor/andromeda/actions/runs/35437883636) on `b15dbe7` | PASS; required jobs completed successfully |
| Live source health | [source-health run 35437889399](https://github.com/artemnoor/andromeda/actions/runs/35437889399), artifact `source-health.json` | PASS; both adapters completed with zero blocking gaps |
| BMSTU live quality | 344 source hashes, 134 identities/programmes, 100% curriculum/admission/taxonomy coverage, 2,817 typed source gaps, 22 diagnostics, decision `degraded`, zero blocking gaps | PASS with explicit degraded source state |
| HSE live quality | 1,493 source hashes, 96 identities/programmes, 88.54% curriculum coverage, 51.04% admission coverage, 84.59% taxonomy coverage, 122 typed source gaps, 122 diagnostics, decision `degraded`, zero blocking gaps | PASS with limited coverage explicitly exposed |
| PostgreSQL/deployment | Clean `b15dbe7` images, disposable PostgreSQL 16, Caddy TLS gateway, direct/public liveness and readiness, fixture ingestion for BMSTU/HSE | PASS; readiness schema `0022_ingestion_concurrency` |
| Browser product smoke | Production-like Caddy endpoint with configured disposable ops key: Chromium + mobile Chromium, 52 tests passed | PASS |
| Persistence recovery | Custom PostgreSQL backup restored into an isolated database; `0022 → 0021` downgrade and `0021 → 0022` upgrade completed | PASS |
| Security/dependencies | Canonical security target: 12 security tests, Python dependency audit with no known vulnerabilities, npm audit with zero vulnerabilities | PASS |
| Documentation/contracts | `scripts/check_docs.py`, OpenAPI drift, deployment artifact contract, strict typing, architecture and boundary gates | PASS |

## Deployment checkpoint

The disposable deployment was built from the clean `b15dbe7` checkout. Image
IDs are recorded for rollback attribution:

- backend `andromeda-backend:b15dbe7` — `sha256:cf011a52875a16a31022eec0e72128b2ea58d44d65f2c49f31a8149e03f72511`;
- frontend `andromeda-frontend:b15dbe7` — `sha256:882a3c579bc4829f71c97ffb76c4e4538be260b95a9b09322ffe2f6510b66c98`;

The public gateway returned HTTPS `live`, HTTPS `ready`, `/api/programs`, and
the frontend root. Plain HTTP returned `308` to HTTPS. The readiness response
reported the expected migration head `0022_ingestion_concurrency`.

Fixture ingestion produced BMSTU and HSE run IDs and projected canonical data
without source gaps for BMSTU; HSE fixture gaps remained typed and visible.

## Rollback and fallback

- Keep the previous tested image checkpoint `7a34edd` available until the
  first post-release source-health run is reviewed.
- Keep the encrypted PostgreSQL backup and the isolated restore procedure
  from the deployment smoke; restore is performed before switching traffic.
- If a migration or source publication fails, retain the last-good canonical
  projection and use the admin run ID/diagnostic record for recovery.
- Roll back to the previous image set and database backup together; do not mix
  an older application image with an unreviewed schema head.

## Known boundaries after promotion

- HSE is supported with partial, source-backed coverage. `degraded` is a
  truthful product state, not a hidden success or a promise of completeness.
- Career Fit and validated Workload Readiness remain out of MVP scope.
- Live source changes, taxonomy review, and operator alert retention remain
  operational follow-up, not reasons to weaken fail-closed behavior.

The corresponding 16-item gate is maintained in
[mvp-production-level-gate.md](mvp-production-level-gate.md). The metadata
generator remains deliberately `NOT_READY` by itself; this human-reviewable
record is the evidence attachment that closes the gate.
