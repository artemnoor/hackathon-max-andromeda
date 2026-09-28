# Proftest Spike retirement

The standalone `proftest-spike` package was an exploratory implementation. Its
production-relevant flows are now owned by `frontend-next` and the canonical
`andromeda.modules.proftest` backend: guest sessions, adaptive questions,
answer persistence, completion, recommendations, and reload recovery.

The executable Spike tree and its duplicate API client were removed from the
repository. The Git history remains the source of traceability for the
exploration; this note intentionally contains no executable instructions,
fixtures, credentials, or copied source payloads.
