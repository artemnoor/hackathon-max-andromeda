# Staging deployment

Andromeda local/demo runs may use SQLite. Staging must use PostgreSQL and an
external domain; serving the application directly on an IP over HTTP is not a
production deployment.

## Required staging configuration

Set these values outside the repository (for example in the deployment
environment file or secret manager):

| Variable | Purpose |
| --- | --- |
| `ANDROMEDA_ENV=staging` | Enables staging safety checks. |
| `ANDROMEDA_DATABASE_URL=postgresql+psycopg://...` | PostgreSQL connection. |
| `ANDROMEDA_DOMAIN=andromeda.example.org` | Caddy hostname and HTTPS. |
| `ANDROMEDA_FRONTEND_ORIGIN` | Optional explicit browser origin for non-default ports or a reverse-proxy origin; defaults to `https://${ANDROMEDA_DOMAIN}`. |
| `ANDROMEDA_OPS_API_KEY` | Protected Ops endpoints. |
| `BACKEND_IMAGE` | Immutable backend image tag or digest. |
| `FRONTEND_IMAGE` | Immutable Next standalone image tag or digest. |

`ANDROMEDA_OPS_API_KEY` must be at least 16 characters and is supplied through
the deployment secret manager. Never copy real values into `.env` committed to
the repository.

## Optional Jev next-action runtime

The backend image includes the pinned TypeSafe SDK, the registered question
definitions and the production calibration lock used by the next-action
decision. The runtime is disabled by default; with no explicit opt-in, the
deterministic policy remains active. Jev may select only a registered,
calibrated next action. Analytics, admission eligibility and factual results
remain deterministic and source-backed.

To let Jev control eligible next-action decisions in staging, set these values
in the external deployment environment file/secret manager (do not commit the
API key):

```dotenv
JEV_ENABLED=true
JEV_SHADOW_ENABLED=false
JEV_CALIBRATION_ENABLED=true
JEV_CALIBRATION_MODE=production
JEV_CALIBRATION_LOCK_PATH=/app/config/jev/locks/next-action.typesafe-jev.v2.lock.json
JEV_CALIBRATION_MAX_AGE_SECONDS=7776000
JEV_RUNTIME_PROVIDER=typesafe
JEV_ENDPOINT=https://polza.ai/api
JEV_MODEL=typesafe/jev
TYPESAFE_API_KEY=<secret>
```

`JEV_API_KEY` is also accepted as a compatibility key name, but configure only
one key. The default calibration artifact age limit is 90 days; refresh and
review the lock before it expires. Rebuild the backend image when the approved
registry or calibration artifact changes. If configuration, artifact
validation, provider health or calibrated confidence fails, runtime startup
or an individual decision falls back safely to the deterministic policy.
Review the capability report after restart; a configured flag alone does not
prove that Jev became active.

The `deploy/yc/compose.yaml` stack runs PostgreSQL, the backend, the Next
frontend and Caddy. Caddy obtains and renews the certificate automatically
once DNS points the domain to the host and ports 80/443 are reachable.

Apply migrations before starting the application image:

```bash
docker compose --env-file /etc/andromeda/backend.env -f deploy/yc/compose.yaml run --rm backend python -m alembic upgrade head
docker compose --env-file /etc/andromeda/backend.env -f deploy/yc/compose.yaml up -d
```

Before a release, validate the resolved compose contract without starting
services:

```bash
docker compose --env-file /etc/andromeda/backend.env -f deploy/yc/compose.yaml config --quiet
```

The tracked packaging gate checks the backend `8020` contract, Next
`/app/server.js` Docker runner, VM/systemd
`frontend-runtime/.next/standalone/server.js`, and Caddy `/api` routing.
The VM release must copy the complete Next standalone directory, not only
`.next/static`. Signed server-side OG rendering uses the frontend-only
`ANDROMEDA_RENDER_HMAC_SECRET` and the internal backend URL.

## Smoke checks

`/api/health/live` checks that the process is running. `/api/health/ready`
checks database reachability and exact compatibility with the image's Alembic head;
it intentionally does not depend on BMSTU/HSE availability.

```bash
curl --fail https://andromeda.example.org/api/health/live
curl --fail https://andromeda.example.org/api/health/ready
curl --fail https://andromeda.example.org/programs
```

Then check one program, curriculum/admissions, a comparison and an anonymous
DecisionContext session in the browser. The scheduled `source-health` workflow
is a separate operational check and does not block pull requests during a
temporary university-site outage.

The disposable fixture smoke is:

```bash
python scripts/andromeda.py production-smoke
```

It does not use an untracked SQLite seed and does not mutate the staging
database. A real staging release additionally requires a PostgreSQL backup,
the current Alembic head, and a restore smoke against an isolated database.

## Backup and restore

Run backups from a host that can reach PostgreSQL. Keep encrypted copies and
retain at least daily backups for the agreed staging retention window.

```bash
pg_dump --format=custom --file=andromeda-$(date +%Y%m%d-%H%M).dump "$ANDROMEDA_DATABASE_URL"
createdb andromeda_restore
pg_restore --clean --if-exists --dbname="$ANDROMEDA_RESTORE_URL" andromeda-YYYYMMDD-HHMM.dump
```

Never put connection strings or dump files in Git. Verify restores regularly
by running `alembic upgrade head`, `/api/health/ready`, and a catalog/decision smoke
check against the restored database.

## Rollback

1. Keep the previous container image tag available.
2. Before a schema migration, take a PostgreSQL dump.
3. Deploy the previous image only when the new migration is backward-compatible
   with that image; otherwise restore the database backup in an isolated
   rollback procedure.
4. Do not edit or delete an applied Alembic revision. Forward-fix with a new
   migration and record the compatibility boundary in the release notes.

For VM/systemd rollback, retain the previous extracted release directory and
image/runtime commit. Switch the symlink only after the previous image is
known to be compatible with the already-applied schema; otherwise restore the
database backup into an isolated target and run the readiness/catalog smoke
before redirecting traffic.
