# Architecture

## Runtime boundary

```text
MAX User
  ├─ Bot ───────────→ MAX Bot Transport Adapter ─────┐
  └─ Mini App ──────→ MAX Bridge + Mini App Host ────┤
                                                      ↓
                                        Future application integration boundary
                                            [not implemented in this phase]
                                                      ↓
                                         Andromeda Public API v1
                                                [NEXT PHASE]

Shared MAX infrastructure (config, logging, security and Redis state) supports both adapters.
```

The repository is a small Node.js modular application. `src/max` owns MAX protocol normalization, SDK access, callbacks, Webhook/polling and deep links. `src/shared` contains bounded configuration, safe errors, redacting logs and ephemeral transport state. `src/web` hosts only the static Mini App shell, health routes and MAX launch proof verification. `miniapp` is a static MAX Bridge adapter and presentational shell.

The MAX platform user ID is not an Andromeda account ID, role, session or authorization grant. `initDataUnsafe` is never used. The Mini App endpoint returns only `{ authenticated: true }`; no account linking, cookie, product data, business command or Andromeda API call exists yet.

Redis is the production shared state owner for rate counters, update leases/completion and one-time deep-link references. Process memory state is bounded and only available in explicit development/test composition. The Bot SDK is accessed in one adapter; subject behavior does not import the SDK.

## Transport and lifecycle

Bot polling processes updates sequentially and advances the polling marker only after the batch succeeds. Webhook handling authenticates a bounded request and acknowledges only after processing completes. Startup checks the current MAX webhook subscription and does not delete a conflicting subscription. Shutdown does not mutate remote MAX subscription state.

The Mini App server has an explicit static-file allowlist, response-size bound, origin allowlist, CSP, and server-side HMAC verification of launch `initData`. Browser data is sent only in a same-origin request header and is not placed in a URL, log, local storage or cookie.

## Deliberately absent

- Andromeda Public API client, API proxy or backend route.
- Product screens, comparison, admission workflows, account linking or persistence of applicant context.
- Additional bounded contexts, database, queue platform or microservices.
- MAX Bot command semantics beyond neutral status/help replies.

Future API calls must use the separately approved Public API v1 contract. Bot and Mini App should remain channel-specific adapters over the same eventual application contract.
