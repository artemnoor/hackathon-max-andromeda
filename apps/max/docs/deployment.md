# Deployment

## Local Compose

`compose.yaml` is a development stack with Bot, Mini App and Redis. Redis is private to the Compose network; the Mini App binds to loopback on the host for local preview. The image builds on Node 22, runs as the non-root `node` user, and the application containers use a read-only root filesystem, dropped Linux capabilities and `no-new-privileges`.

```powershell
Copy-Item .env.example .env
# Set MAX_BOT_TOKEN in .env
docker compose up --build
```

Do not use this local Compose Redis setup as protected production state. Protected config requires Webhook mode, verified TLS Redis (`rediss:`), a public Mini App origin, a long independent Webhook secret and a randomly generated 32-byte base64url deep-link signing key.

## Production prerequisites

Production deployment is not included. An external TLS ingress/reverse proxy must expose the Mini App and forward only the configured Webhook path to the Bot service. Keep Redis private and use TLS with certificate verification. Configure `MINI_APP_ORIGINS` to the exact public origin(s); do not use wildcard CORS. Set secrets using the deployment platform secret store, never a committed env file.

The current app has no backend API dependency. Health routes indicate process readiness only; they do not certify MAX or Andromeda availability.
