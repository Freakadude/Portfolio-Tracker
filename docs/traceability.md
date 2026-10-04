# Traceability

Requirement ID → module → test → status (`todo`, `in progress`, `done`).

## Phase 0 — Foundations

| ID | Module | Test | Status |
| --- | --- | --- | --- |
| FR-SY-01 | folio/api/routers/setup, web/src/pages/Setup.tsx | tests/integration/test_setup.py, web/e2e/setup-wizard.spec.ts | done |
| FR-SY-02 | folio/api/routers/auth, folio/security | tests/integration/test_auth.py | done |
| FR-SY-05 | folio/security/secrets, redact (done) | tests/integration/test_secrets.py, test_settings.py, test_logging.py | done |
| FR-SY-09 (shell) | folio/api/routers/settings, folio/settings_schema.py, web/src/pages/Settings.tsx | tests/integration/test_settings.py, web/src/app.test.tsx, web/e2e/setup-wizard.spec.ts | done |
| NFR-07 | folio/api/middleware (CSP, CSRF), docker/Dockerfile, docker-compose.yml | tests/integration/test_security_headers.py, test_deploy_config.py; multi-arch image build in CI (passed) | done |
| NFR-09 | folio/logging, folio/api/routers/health (Prometheus /metrics is optional, not built) | tests/integration/test_health.py, test_logging.py | done |
| NFR-10 | .github/workflows/ci.yml, .pre-commit-config.yaml, pyproject.toml, web/eslint.config.js | CI workflow: ruff, mypy, pytest, pip-audit, eslint, vitest, npm audit, e2e, gitleaks | done |
| NFR-01 (groundwork) | folio/db/types | tests/unit/test_decimal_type.py | done |

## Phase 1 — Ledger and prices

| ID | Module | Test | Status |
| --- | --- | --- | --- |
| NFR-01 | folio/domain (no floats; Decimal end to end) | tests/unit/domain/test_ledger_properties.py (no-floats test, invariants), test_ledger_golden.py | in progress (domain done; services and API pending) |
| FR-TX-03 | folio/domain/ledger.py (FIFO and AVG), account method switch in ledger_service | tests/unit/domain/test_ledger_golden.py, tests/integration/test_transactions_api.py | done |
| FR-TX-04 | folio/domain/ledger.py preview_sell, POST /transactions/preview-sell | tests/unit/domain/test_ledger_golden.py, test_ledger_properties.py, tests/integration/test_transactions_api.py | in progress (UI pending) |
| FR-INS-01 | folio/marketdata/resolve.py, isin.py, folio/api/routers/instruments.py | tests/integration/test_instruments_api.py (recorded OpenFIGI and Yahoo responses) | in progress (UI pending) |
| FR-INS-02 | folio/instruments.py (manual instruments), prices endpoint | tests/integration/test_instruments_api.py | in progress (UI pending) |
| FR-INS-03 | folio/instruments.py (edit, archive, delete) | tests/integration/test_instruments_api.py | in progress (UI pending) |
| FR-MD-01 | folio/marketdata/base.py (provider interface), fake.py | tests/integration/test_marketdata_fallback.py | done (jobs that use it follow) |
| FR-MD-10 | folio/marketdata/budget.py (UsageTracker), http.py | tests/integration/test_marketdata_http.py | in progress (usage endpoint pending) |
| FR-MD-11 | folio/marketdata/fallback.py, registry.py, prices.py (is_stale) | tests/integration/test_marketdata_fallback.py, test_marketdata_prices.py | in progress (stale marker in the UI pending) |
| FR-MD-02 | folio/marketdata/exchanges.py (calendars, job times), folio/jobs/market.py eod_job | tests/unit/test_exchanges.py, tests/integration/test_jobs_market.py | in progress (APScheduler registration pending) |
| FR-MD-03 | folio/jobs/market.py backfill_job | tests/integration/test_jobs_market.py | in progress (queued from instrument add, pending) |
| FR-MD-04 | folio/marketdata/prices.py (gaps, overrides), gap_job | tests/integration/test_marketdata_prices.py, test_jobs_market.py | done |
| FR-MD-06 | folio/marketdata/fx.py, ecb.py | tests/integration/test_marketdata_fx.py | done |
| FR-MD-07 | folio/marketdata/corporate_actions.py, folio/api/routers/corporate_actions.py, ledger_service.confirm_draft, jobs actions_job | tests/integration/test_corporate_actions.py (1:4 split quadruples quantity and keeps cost; dividend drafts) | in progress (Insights UI pending; weekly schedule pending) |
| FR-TX-01 | folio/ledger_service.py, folio/api/routers/transactions.py | tests/integration/test_transactions_api.py | in progress (UI pending) |
| FR-TX-02 | folio/ledger_service.py (ECB prefill, override), fx-prefill endpoint | tests/integration/test_transactions_api.py | in progress (UI pending) |
| FR-TX-05 | folio/positions.py, folio/api/routers/positions.py | tests/integration/test_positions_api.py (hand-computed metrics; reconciliation with invariants 1 and 2) | in progress (UI pending) |
| FR-TX-06 | folio/ledger_service.py (rebuild, snapshot requests), folio/jobs/portfolio.py | tests/integration/test_transactions_api.py, test_portfolio.py (a backdated buy changes historical snapshots) | done |
| FR-TX-07 | folio/imports/, folio/api/routers/imports.py | tests/integration/test_imports_api.py (fictional Dutch and English Degiro-shaped exports, comma decimals, re-import adds 0 rows, undo) | in progress (wizard UI pending) |
| FR-PF-01 | folio/analytics/valuation.py, folio/portfolio.py, folio/api/routers/portfolio.py (summary) | tests/unit/analytics/test_valuation.py, tests/integration/test_portfolio.py (hand-computed periods) | in progress (overview UI pending) |
| FR-PF-10 | folio/portfolio.py (save_snapshots, lock_closed_years), folio/jobs/portfolio.py | tests/integration/test_portfolio.py (idempotent re-run; 1 January flagged and locked) | in progress (nightly schedule pending) |
| FR-SY-06, FR-SY-07 (CLI restore) | folio/backup, folio/cli | - | todo |
| FR-SY-08 | folio/audit; instruments, transactions, accounts, prices, settings audited | tests/integration/test_settings.py, test_instruments_api.py, test_transactions_api.py | in progress (viewer pending) |
| NFR-02 | UTC storage (UTCDateTime), exchange-local trading dates (Date columns), migration 0002 | tests/integration/test_schema.py | in progress (schema done; job scheduling in exchange time pending) |
