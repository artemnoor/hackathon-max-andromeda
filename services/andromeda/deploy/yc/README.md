# YC deployment

The cheapest supported live layout is one small Compute Cloud VM:

```text
domain :443 → Caddy (automatic HTTPS) → frontend:3000
                         ├→ /api/v1/* → backend:8020 (version path preserved)
                         └→ /api/* → backend:8020 (legacy prefix stripped)
```

`https://${ANDROMEDA_DOMAIN}/openapi.json` serves the canonical, client-facing
Public API v1 contract from `../../openapi.json`. It intentionally does not
proxy FastAPI's full runtime schema, which includes internal operator/admin
operations. The public URL is configured in `DATA-API.yaml`.

For the existing Nginx host, install the canonical snapshot at
`/opt/andromeda/public/openapi.json` and serve it from this exact location in
the TLS server block:

```nginx
location = /openapi.json {
    default_type application/json;
    add_header Cache-Control "public, max-age=300" always;
    alias /opt/andromeda/public/openapi.json;
}
```

Install and enable the low-cost one-minute monitor with:

```sh
sudo install -o root -g www-data -m 0644 openapi.json /opt/andromeda/public/openapi.json
sudo install -o root -g root -m 0644 deploy/yc/public-api-monitor.py /opt/andromeda/public-api-monitor.py
sudo install -o root -g root -m 0644 deploy/yc/andromeda-public-api-monitor.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/yc/andromeda-public-api-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now andromeda-public-api-monitor.timer
```

The monitor checks liveness, the non-empty programs catalog and the public
OpenAPI document over HTTPS once per minute; results are recorded in the
system journal.

Staging uses PostgreSQL through `ANDROMEDA_DATABASE_URL`; schema upgrades run
through Alembic before the backend starts. Keep database credentials only in
the deployment environment, never in this repository.

`compose.yaml` expects `BACKEND_IMAGE` and `FRONTEND_IMAGE` in
`/opt/andromeda/.env`. Signed server-side OG renderer routes require
`ANDROMEDA_RENDER_HMAC_SECRET`; it is provided only to the frontend service
and must remain in the deployment secret manager.
The backend trusted browser origin defaults to `https://${ANDROMEDA_DOMAIN}`;
set `ANDROMEDA_FRONTEND_ORIGIN` explicitly when a reverse proxy exposes a
non-default origin or port (for example, a local TLS smoke).
Jev next-action control is optional and remains off unless `JEV_ENABLED=true`
and its production calibration gate/key are configured; see
[`docs/deployment.md`](../../docs/deployment.md#optional-jev-next-action-runtime).
The image carries the pinned SDK, question registry and matching calibration
lock. Keep the provider key only in `/opt/andromeda/.env` or the secret manager.
The frontend is built with `NEXT_PUBLIC_API_BASE_URL=/api`, so its user-facing
requests reach `/api/v1/*` on the same origin. The gateway preserves that
versioned path for the backend and continues stripping `/api` for legacy
unversioned admin routes. The public site does not expose an internal VM
address or need CORS for normal same-origin use.
Server-side OG routes use the explicit runtime variable
`ANDROMEDA_INTERNAL_API_URL=http://backend:8020`; they never use the public
browser path or a `backend:8000` fallback.

The local/demo compose profile may use SQLite for a cheap single-process run,
but it is not the staging target. Staging requires a domain configured in
Caddy, automatic HTTPS, PostgreSQL backups, and the readiness check at
`/api/health/ready`. Canonical programs, Andromeda account/profile state and
decision scoring remain backend-owned. The MAX Bot and Mini App are implemented
in the separate `apps/max/` runtime and use this same Public API v1 boundary.
The Mini App also keeps applicant-entered profile and EGE state in the browser;
it is not synchronized to the Andromeda profile. See the [MAX architecture
notes](../../../../apps/max/docs/architecture.md). Any MAX deployment should
preserve the Public API v1 boundary.
