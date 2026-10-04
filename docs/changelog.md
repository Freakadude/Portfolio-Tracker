# Changelog

## Phase 1 — Ledger and prices (in progress)

- Ledger domain: lots, FIFO and average cost, splits, transfers, income and cash flows, sell preview, position and portfolio metrics; property tests for invariants 1-5 and hand-computed golden scenarios; 85 percent coverage gate on `domain/` and `analytics/` in CI [FR-TX-03, FR-TX-04, NFR-01]. See ADR 0005.
- Schema (migration 0002): instrument, listing, ledger_transaction (table name avoids the SQL keyword), lot, lot_match, position, corporate_action, import batches and presets, price_bar, fx_rate, portfolio_snapshot, provider_call, job_request and job_run. A partial unique index on (account, external_ref) makes imports idempotent and lets an undone import be re-run. A test fails if models and migrations drift apart [NFR-02].
- Market-data providers: provider interface, Yahoo, EODHD, Twelve Data, OpenFIGI and ECB adapters, retry with backoff, per-provider daily call budgets, circuit breaker, ordered fallback with the source recorded on every result; Yahoo on by default. Recorded real responses for Yahoo, OpenFIGI and ECB [FR-MD-01, FR-MD-10, FR-MD-11]. See ADR 0006.
- ECB FX service (last earlier rate on weekends and holidays), exchange calendars and EOD job times (two hours after the close, none on closed days), price service (idempotent storage, protected manual overrides with audit, gap detection and repair, staleness after 3 trading days), and the eod, fx, gap and backfill jobs with a `job_run` record and job ID per run [FR-MD-02, 03, 04, 06, 11, FR-INS-02]. See ADR 0007.
- Instruments: resolve an ISIN to Xetra, Euronext and other listings with the trading currency confirmed by a provider (flagged as a guess otherwise), ISIN check-digit validation, manual hand-priced instruments with audited price entry, edit, archive, and delete that is refused while transactions use the instrument and lists them; re-adding a deleted ISIN restores its history. Adding an instrument queues a price backfill [FR-INS-01, FR-INS-02, FR-INS-03]. See ADR 0008.
- Transactions: create, edit, delete for all eleven types with plain-language validation, ECB-prefilled FX that the owner can override (fees and taxes in their own currency), sell preview equal to the saved result, oversell rejection with nothing saved, automatic rebuild of lots, matches and positions, per-account FIFO or average-cost with an audited switch, drafts kept out of the ledger, filtered and paginated listing, accounts API [FR-TX-01, FR-TX-02, FR-TX-03, FR-TX-04, FR-TX-06, FR-SY-08]. See ADR 0009.
- Web client schema regenerated; `web/openapi.json` is now committed and a test fails when the API changes without regenerating it (CI already did) [NFR-10].
- Positions: market value, unrealized and realized P&L, income, total return, day change (EUR and trading currency), weights and stale markers joined at read time; valuation at any past date; position detail with lots, lot matches explaining realized P&L, and history; positions without a price are listed with empty market figures instead of guesses [FR-TX-05].
- CSV import backend: upload with encoding and delimiter detection, column mapping with auto-detection (including Degiro's unnamed currency columns), comma decimals and thousands separators, dry run with new, duplicate, error and skipped rows (unknown ISINs, bad cells, oversells), all-or-nothing commit, idempotent re-import, undo of a whole batch, saved presets [FR-TX-07]. See ADR 0010.
- Fixed: a request that touched a provider while holding an open database write could fail with "database is locked" (session update committed early; FX catch-up fetches before writing).

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
