# Tracer namespace migration checkpoint

**Checkpoint:** MVP-012
**Baseline:** `4088116`
**Disposition rule:** a tracer-named hit is not removed by search-and-delete;
it is classified as canonical compatibility, intentional raw contract,
historical/untracked artifact, or migrated runtime.

| Hit | Disposition | Evidence / removal condition |
| --- | --- | --- |
| `backend/scripts/run_andromeda_bmstu.py` | `REPLACE` / canonical | Owns BMSTU capture → validation → Alembic → projection and imports the canonical composition root. |
| `backend/scripts/run_andromeda_demo.py` | `REPLACE` / canonical | Owns API/frontend process lifecycle and catalog/compare/admission/events/campus smoke. |
| `backend/scripts/run_tracer_bullet.py` | `LEAVE` / one-cycle compatibility | Thin exports/CLI wrapper; parity is asserted by `backend/tests/scripts/test_tracer_compatibility.py`; remove only after the next clean-checkout migration checkpoint. |
| `backend/scripts/run_tracer_demo.py` | `LEAVE` / one-cycle compatibility | Thin wrapper preserving old imports and monkeypatch surface; canonical demo test no longer imports it; remove only after wrapper parity and documented command migration are complete. |
| `RawTracerBundle` and `backend/src/andromeda/ingestion/contracts/raw.py` | `LEAVE` / intentional current contract | Shared typed raw boundary used by BMSTU/HSE adapters and validation; renaming for appearance would change a real contract without product value. |
| `backend/src/andromeda/ingestion/universities/bmstu/parser/tracer.py` | `LEAVE` / intentional adapter parser module | The module is a BMSTU parser implementation, not an executable spike; its logger namespace was migrated to `andromeda.ingestion.bmstu.parser`. |
| `backend/tests/fixtures/tracer/raw` | `LEAVE` / intentional fixture namespace | Commit-controlled raw fixture boundary used by baseline evidence; the fixture name is part of existing tests and is not a production runtime. |
| `backend/tests/scripts/test_tracer_*.py` and `backend/tests/integration/test_tracer_bullet.py` | `LEAVE` / compatibility regression labels | The scripts tests now import canonical runner symbols; filenames preserve the historical regression identity until a separate test-file rename checkpoint. |
| `tracer.source.*` and `tracer.parser` loggers | `REPLACE` / migrated | Logger names now use `andromeda.ingestion.bmstu.*`; no runtime logger under the old prefix remains in source. |
| `backend/Dockerfile` seed copy and `backend/docker-entrypoint.sh` `tracer.db` bootstrap | `REPLACE` / migrated | Runtime image no longer copies or initializes an untracked SQLite seed; entrypoint fails closed unless an explicit PostgreSQL `ANDROMEDA_DATABASE_URL` is present. |
| `backend/data/tracer.db` | `LEAVE` / untracked local artifact | Existing user-generated data was not deleted or rewritten. It is no longer referenced by the runtime image; cleanup/archive requires a separate explicit decision. |
| `backend/src/bmstu_andromeda_parser.egg-info/PKG-INFO` | `LEAVE` / generated untracked metadata | Stale generated metadata is not a runtime source; clean package installation regenerates it. It is preserved because it pre-existed as an untracked user artifact. |
| `proftest-spike/` | `LEAVE` / retired historical workspace | Runtime manifests/imports are absent and `docs/archive/proftest-spike.md` is the historical record; this untracked directory is not deleted in MVP-012. |
| `BMSTU_DATABASE_URL` | `LEAVE` / bounded environment compatibility | Settings/Alembic still support a deprecated fallback for one migration cycle; canonical docs and new runner use `ANDROMEDA_DATABASE_URL`. Remove only after environment migration evidence. |

## Parity checkpoint

The canonical runner preserves the old public result fields (`runId`, source
hashes, event/campus/admission counters), CLI flags, source adapter registry,
fixture/live modes, and process lifecycle. The following tests are the
executable parity evidence:

```powershell
cd backend
python -m pytest -q tests/scripts/test_tracer_compatibility.py tests/scripts/test_tracer_events_runner.py tests/scripts/test_tracer_campus_runner.py tests/integration/test_demo_runner.py tests/integration/test_bmstu_full_ingestion.py
```

The old wrappers must not be used by new runtime code. A repository-wide hit
scan is allowed to find only this inventory, the compatibility wrappers/tests,
the intentional raw contract/fixture, and the deprecated environment fallback
until the later cleanup checkpoint.
