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
| FR-TX-03 | folio/domain/ledger.py (FIFO and AVG); account switch in ledger service pending | tests/unit/domain/test_ledger_golden.py | in progress |
| FR-TX-04 | folio/domain/ledger.py preview_sell; API pending | tests/unit/domain/test_ledger_golden.py, test_ledger_properties.py | in progress |
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
| FR-MD-07 | folio/marketdata/corporate_actions | - | todo |
| FR-TX-01, 02, 05, 06 | folio/ledger_service, folio/api (transactions, positions) | - | todo |
| FR-TX-07 | folio/imports | - | todo |
| FR-PF-01, FR-PF-10 | folio/analytics/valuation, snapshot job | - | todo |
| FR-SY-06, FR-SY-07 (CLI restore) | folio/backup, folio/cli | - | todo |
| FR-SY-08 | folio/audit (helper done), audit viewer API and UI | tests/integration/test_settings.py (settings audit) | in progress |
| NFR-02 | UTC storage (UTCDateTime), exchange-local trading dates (Date columns), migration 0002 | tests/integration/test_schema.py | in progress (schema done; job scheduling in exchange time pending) |
