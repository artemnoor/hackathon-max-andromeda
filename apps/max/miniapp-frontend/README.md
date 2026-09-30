# Andromeda Admissions Mini App

This directory is the source of [`artemnoor/andromeda-admissions-frontend`](https://github.com/artemnoor/andromeda-admissions-frontend), cloned at commit `841fb006fb031c7e321ba0be4d064086adc659f5` and adapted for the MAX Mini App. The full original project structure, styles and assets are here. The host serves the Vite production build from `dist`; the former `apps/max/miniapp` shell is no longer served.

The original standalone `/v1` client and demo records are outside the active build. `src/main.js` now mounts the original app shell and program card component using real Andromeda catalog data. `src/api/client.js` calls the MAX host's signed, same-origin proxy to canonical Andromeda Public API v1 for programs, universities, curriculum, published admission offerings and comparison. Only these source-backed surfaces appear in the active navigation. Profile, shortlist, recommendations, events and personal route need real contracts and persistence before they can be enabled in MAX.

Build from `apps/max` with `npm run build:miniapp`; run the host with `npm run dev:miniapp`. Set `ANDROMEDA_API_BASE_URL` on the MAX host to the reachable backend. Expose the host through HTTPS, add its public origin to `MINI_APP_ORIGINS`, and set `MINI_APP_PUBLIC_URL` to the same origin to display the native MAX launch button. Do not put API secrets or MAX tokens into Vite environment variables. Open the app from MAX so each request carries signed launch data in `X-Max-Init-Data`; the browser does not store that proof.

The original `docs/api/openapi.yaml` describes the upstream standalone prototype and is not the MAX contract. The canonical client contract is `services/andromeda/openapi.json`, with generated DTOs under `apps/max/src/andromeda/generated`.
