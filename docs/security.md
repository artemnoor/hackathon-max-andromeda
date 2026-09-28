# Security

## Launch and identity boundary

The server validates MAX Mini App `initData` signature and age on each request that uses it. The verifier returns no profile object or identity. `initDataUnsafe` is untrusted display data and is not read. No Andromeda account is linked and no authorization role is inferred from the MAX identity.

## Bot and state

Bot updates are normalized into bounded typed values; profile and full attachment payloads are discarded. Webhook requests use an exact secret, content-type/method/path checks and a body cap. MAX API calls pin the official HTTPS origin, reject redirects, bound response size/time, and retry only safe GET requests. Redis provides atomic update leases, rate limits and one-time deep-link consumption; protected environments fail closed on Redis errors.

## Web boundary and secrets

The Mini App host serves an explicit file allowlist with size/path bounds, strict CSP, exact CORS origins and no credentialed CORS. Launch proof is sent in a request header, never query parameters. Logs redact tokens, initData, user/chat IDs and payloads. Store runtime credentials outside source control and rotate any credential that may have been exposed.

Report a vulnerability privately to the repository owner; do not include real MAX tokens, launch data, user identifiers or Redis credentials in an issue or test fixture.
