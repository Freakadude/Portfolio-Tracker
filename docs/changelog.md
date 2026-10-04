# Changelog

## Unreleased

### Phase 0 — Foundations
- Repo conventions: CLAUDE.md, ADRs, traceability, shared Claude Code permission rules.
- Python 3.12 uv project, ruff/mypy/pytest config, settings, SQLite engine (WAL) and `DecimalText` type with property tests [NFR-01].
- Auth: Argon2id passwords, DB-backed sessions (HttpOnly, SameSite=Strict, Secure over HTTPS, 30-day remember), persisted login throttle (5 failures / 15 min), CSRF double-submit cookie, CSP and security headers, RFC 9457 errors, Alembic migration 0001 [FR-SY-02, NFR-07].
- Encrypted secret store (Fernet, HKDF-derived key), masked display, redacted repr [FR-SY-05].
- Setup wizard API (owner, first account, complete) and typed settings sections with masked write-only secrets and audit diffs; audit-log helper [FR-SY-01, FR-SY-09, FR-SY-05, FR-SY-08].
- JSON logging with request IDs and secret scrubbing, `/healthz` and `/readyz`, CLI (`init`, `migrate`, `create-user`, `reset-password`, `web`, `worker` stub), healthcheck probe, built-UI serving [NFR-09, FR-SY-05].
- Web shell (React, Vite, Tailwind): login, 5-step setup wizard, app shell with empty states for every page, generic settings pages with masked secrets, light/dark themes, i18n layer (English), generated API client, Vitest and Playwright tests [FR-SY-01, FR-SY-09, NFR-10].
- SQLite folder is created automatically for file databases.
