# Changelog

## Phase 1 — Ledger and prices (in progress)

- Ledger domain: lots, FIFO and average cost, splits, transfers, income and cash flows, sell preview, position and portfolio metrics; property tests for invariants 1-5 and hand-computed golden scenarios; 85 percent coverage gate on `domain/` and `analytics/` in CI [FR-TX-03, FR-TX-04, NFR-01]. See ADR 0005.

## Phase 0 — Foundations (2026-10-04)

Released as the state of `main` after the commit "ci: pin GitHub Actions to exact release tags". CI green: 60 Python tests, 6 web tests, 2 Playwright tests, multi-arch image build, pip-audit and npm audit clean, gitleaks clean. Requirements closed: FR-SY-01, FR-SY-02, FR-SY-05, FR-SY-09 (shell), NFR-01 (groundwork), NFR-07, NFR-09, NFR-10.

Not yet verified: the compose stack has not been run (Docker is not installed on the dev machine, ADR 0003). Gate check for the owner: deploy the stack through Portainer on the LXC, then open `/healthz` and the setup wizard over the LAN or tailnet.

- Repo conventions: CLAUDE.md, ADRs, traceability, shared Claude Code permission rules.
- Python 3.12 uv project, ruff/mypy/pytest config, settings, SQLite engine (WAL) and `DecimalText` type with property tests [NFR-01].
- Auth: Argon2id passwords, DB-backed sessions (HttpOnly, SameSite=Strict, Secure over HTTPS, 30-day remember), persisted login throttle (5 failures / 15 min), CSRF double-submit cookie, CSP and security headers, RFC 9457 errors, Alembic migration 0001 [FR-SY-02, NFR-07].
- Encrypted secret store (Fernet, HKDF-derived key), masked display, redacted repr [FR-SY-05].
- Setup wizard API (owner, first account, complete) and typed settings sections with masked write-only secrets and audit diffs; audit-log helper [FR-SY-01, FR-SY-09, FR-SY-05, FR-SY-08].
- JSON logging with request IDs and secret scrubbing, `/healthz` and `/readyz`, CLI (`init`, `migrate`, `create-user`, `reset-password`, `web`, `worker` stub), healthcheck probe, built-UI serving [NFR-09, FR-SY-05].
- Web shell (React, Vite, Tailwind): login, 5-step setup wizard, app shell with empty states for every page, generic settings pages with masked secrets, light/dark themes, i18n layer (English), generated API client, Vitest and Playwright tests [FR-SY-01, FR-SY-09, NFR-10].
- SQLite folder is created automatically for file databases.
- Container and CI: multi-stage Dockerfile (non-root, read-only root fs), Portainer-ready docker-compose.yml, GitHub Actions (python, web with e2e, multi-arch image build, gitleaks), pre-commit hooks (gitleaks, ruff, eslint, prettier), `.gitattributes` for LF line endings [NFR-07, NFR-10].
