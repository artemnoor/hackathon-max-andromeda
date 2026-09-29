# Security policy

Report vulnerabilities privately to the repository owner rather than opening a public issue containing exploit details or personal data.

Never commit credentials, `.env` files, MAX init data, cookies, raw platform updates, applicant profiles, or provider request/response logs. MAX authentication must validate signed init data server-side. MAX platform identifiers must not be treated as Andromeda account identities. All backend access from MAX must use the allowlisted Public API v1 HTTP client.

Source ingestion must retain the backend's URL allowlist, redirect validation, bounded downloads and content checks. AI providers remain optional and must not become a source of canonical facts or deterministic eligibility decisions.
