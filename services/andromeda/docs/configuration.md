[← Admission Fit](admission-fit.md) · [Back to README](../README.md) · [PostgreSQL →](postgresql.md)

# Конфигурация

Настройки читаются через `andromeda.infrastructure.config.Settings`. Примеры переменных находятся в `backend/.env.example`, `.env.development.example`, `.env.staging.example` и `frontend-next/.env.example`.

| Переменная | Компонент | По умолчанию | Назначение |
|---|---|---|---|
| `ANDROMEDA_ENV` | backend | `test` | Окружение: `test`, `development`, `staging` или `production`; non-test требует PostgreSQL |
| `ANDROMEDA_DATABASE_URL` | backend | SQLite fallback | Единый SQLAlchemy storage target для API, Alembic и generic ingestion; имеет приоритет |
| `ANDROMEDA_DB_POOL_SIZE` | backend | `5` | PostgreSQL connection pool size |
| `ANDROMEDA_DB_MAX_OVERFLOW` | backend | `10` | Дополнительные PostgreSQL connections |
| `ANDROMEDA_DB_POOL_TIMEOUT` | backend | `30` | Ожидание connection из pool, seconds |
| `ANDROMEDA_DB_POOL_RECYCLE` | backend | `1800` | Connection recycle interval, seconds |
| `FRONTEND_ORIGIN` | backend | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated trusted CORS/CSRF origins |
| `LOG_LEVEL` | backend | `INFO` | logging level |
| `ANDROMEDA_PROFILE_COOKIE_NAME` | backend | `andromeda_profile_session` | Anonymous profile cookie name |
| `ANDROMEDA_PROFILE_COOKIE_MAX_AGE` | backend | `2592000` | Browser cookie lifetime, seconds |
| `ANDROMEDA_PROFILE_TTL_SECONDS` | backend | `2592000` | Persisted profile retention, seconds |
| `ANDROMEDA_PROFILE_COOKIE_SECURE` | backend | `false` in test/dev, `true` in staging/production | Require HTTPS for the profile cookie |
| `ANDROMEDA_PROFILE_COOKIE_SAMESITE` | backend | `lax` | Cookie SameSite policy (`lax`, `strict`, `none`; `none` requires Secure) |
| `ANDROMEDA_AUTH_COOKIE_NAME` | backend | `andromeda_auth_session` | Auth session cookie name |
| `ANDROMEDA_AUTH_COOKIE_MAX_AGE` | backend | `2592000` | Auth cookie lifetime, seconds |
| `ANDROMEDA_AUTH_SESSION_TTL_SECONDS` | backend | `2592000` | Server-side session expiry, seconds |
| `ANDROMEDA_AUTH_COOKIE_SECURE` | backend | `false` in test/dev, `true` in staging/production | Require HTTPS for auth cookie |
| `ANDROMEDA_AUTH_COOKIE_SAMESITE` | backend | `lax` | Auth cookie SameSite policy; `none` requires Secure |
| `ANDROMEDA_AUTH_PASSWORD_MIN_LENGTH` | backend | `12` | Registration password minimum |
| `ANDROMEDA_OPS_API_KEY` | backend | — | Required secret for protected Ops endpoints in staging/production; never log it |
| `ANDROMEDA_RATE_LIMIT_WINDOW_SECONDS` | backend | `60` | Process-local sliding-window duration for abuse controls |
| `ANDROMEDA_AUTH_RATE_LIMIT_MAX` | backend | `10` | Requests per window for login/register/guest import per client key |
| `ANDROMEDA_SENSITIVE_RATE_LIMIT_MAX` | backend | `120` | Requests per window for decision/proftest state mutations |
| `ANDROMEDA_OPS_RATE_LIMIT_MAX` | backend | `10` | Requests per window for Ops endpoints per client key |
  | `JEV_ENABLED` | backend | `false` | Enable calibrated production Jev decisions through the TypeSafe SDK; requires key, health and production lock |
| `JEV_SHADOW_ENABLED` | backend | `false` | Run TypeSafe decisions for aggregate comparison while returning deterministic decisions |
| `JEV_CALIBRATION_ENABLED` | backend | `false` | Explicit calibration gate required by production Jev |
| `JEV_CALIBRATION_LOCK_PATH` | backend | — | Environment/secret-manager path to a validated production decision lock |
| `TYPESAFE_API_KEY` | backend | — | Optional provider secret; never commit or log. `JEV_API_KEY` is a supported alias |
  | `JEV_ENDPOINT` | backend | `https://api.typesafe.ai` | Fixed allow-listed TypeSafe-compatible endpoint; `https://polza.ai/api` is supported. Never user-controlled. `JEV_BASE_URL` is a supported alias |
| `JEV_MODEL` | backend | `jev-latest` | TypeSafe model identity |
| `JEVQL_ENABLED` | backend | `false` | Optional bounded semantic predicate runtime |
| `JEV_TREE_ENABLED` | backend | `false` | Optional isolated Node 22 hierarchical resolver |
| `JEV_MAX_ROWS` | backend | `100` | Hard external predicate row budget |
| `JEV_MAX_CHARS` | backend | `32000` | Hard external payload budget |
| `JEV_TIMEOUT_SECONDS` | backend | `2.0` | Interactive provider timeout |
| `JEV_MAX_CONCURRENCY` | backend | `4` | External decision concurrency cap |
| `NEXT_PUBLIC_API_BASE_URL` | frontend-next | `/api` | Browser API base URL; local demo runner overrides it with the API origin |
| `ANDROMEDA_INTERNAL_API_URL` | frontend-next | `http://backend:8020` in YC compose | Server-side Next.js → backend URL; browser calls remain same-origin `/api` |
| `NEXT_PUBLIC_DEBUG_API` | frontend-next | `0` | Client diagnostics toggle; production remains quiet |
| `ANDROMEDA_RENDER_HMAC_SECRET` | frontend-next | — | Secret authorizing signed server-side OG renderer requests |

Для повторяемого fixture-запуска database URL можно передать явно:

```powershell
python backend/scripts/run_andromeda_ingestion.py --university all --mode fixture --database-url sqlite:///./data/andromeda.db
```

`BMSTU_DATABASE_URL` и `BMSTU_DB_*` временно поддерживаются как deprecated fallback для обратной совместимости.
`LOG_LEVEL=DEBUG` включает технические stage-сообщения, но raw response body, PDF text и signed query strings в логах не выводятся.

University admin не требует новых секретов: account session передаётся через
существующую HttpOnly auth cookie. Bootstrap membership использует уже
настроенный `ANDROMEDA_OPS_API_KEY` и endpoint `/ops/university-admin/members`;
ключ не передаётся в браузер и не сохраняется в frontend storage. После
provisioning владелец назначает editor/viewer через scoped console.

В development/staging/production credentials передаются только через environment или secret manager. Staging/production требуют явный `FRONTEND_ORIGIN`, PostgreSQL, `ANDROMEDA_OPS_API_KEY` и secure cookies; production дополнительно принимает только HTTPS origins. Database URL в логах редактируется до `dialect://host:port/database`; password и query parameters не выводятся. SQLite fallback предназначен только для быстрых тестов.

Profile persistence is anonymous by default: the server creates an opaque HttpOnly cookie, stores only its SHA-256 hash, and expires the profile after `ANDROMEDA_PROFILE_TTL_SECONDS`. The browser must not copy this cookie into LocalStorage or JavaScript state. Use `Secure=true` with HTTPS in staging; local HTTP development keeps it `false`.

Jev rollout, lock requirements, degraded behavior and security boundaries are
documented in [Jev rollout and security gate](architecture/jev-rollout.md).

Account sessions are persistent server-side rows with revocation and expiry. Profile binding is deterministic: anonymous-only transfers, account profile wins on conflict, and no field-level merge occurs. State-changing auth calls with an `Origin` header require a configured `FRONTEND_ORIGIN` value.

## See Also

- [Быстрый старт](getting-started.md) — установка и запуск.
- [Архитектура](architecture.md) — infrastructure boundary.
- [PostgreSQL](postgresql.md) — dev/staging database runbook.
- [Тестирование](testing.md) — CI variables and commands.
