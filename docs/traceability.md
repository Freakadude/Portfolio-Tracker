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
| NFR-01 | folio/domain (no floats; Decimal end to end) | tests/unit/domain/test_ledger_properties.py (no-floats test, invariants), test_ledger_golden.py | done (domain, services, API and web numbers all Decimal or string; the web converts rates with BigInt, web/src/lib/decimal.test.ts) |
| FR-TX-03 | folio/domain/ledger.py (FIFO and AVG), account method switch in ledger_service, web AccountsTab (warning before recalculating) | tests/unit/domain/test_ledger_golden.py, tests/integration/test_transactions_api.py, web/src/overview.test.tsx, web/e2e/05-overview-and-system.spec.ts (average cost leaves 320,40 where FIFO leaves 360,60) | done |
| FR-TX-04 | folio/domain/ledger.py preview_sell, POST /transactions/preview-sell | tests/unit/domain/test_ledger_golden.py, test_ledger_properties.py, tests/integration/test_transactions_api.py, web/src/transaction-form.test.tsx, web/e2e/03-transactions.spec.ts (hand-computed sale across two lots, oversell explained) | done |
| FR-INS-01 | folio/marketdata/resolve.py, isin.py, folio/api/routers/instruments.py | tests/integration/test_instruments_api.py (recorded OpenFIGI and Yahoo responses) | done |
| FR-INS-02 | folio/instruments.py (manual instruments), prices endpoint, web AddInstrumentDialog | tests/integration/test_instruments_api.py, web/e2e/02-instruments.spec.ts | done |
| FR-INS-03 | folio/instruments.py (edit, archive, delete), web InstrumentsTab | tests/integration/test_instruments_api.py, web/src/holdings.test.tsx (blocking transactions shown) | done |
| FR-MD-01 | folio/marketdata/base.py (provider interface), fake.py | tests/integration/test_marketdata_fallback.py | done (jobs that use it follow) |
| FR-MD-10 | folio/marketdata/budget.py (UsageTracker), http.py, GET /system/usage | tests/integration/test_marketdata_http.py, test_system_api.py (usage matches the counter exactly) | done (web System page tested in web/src/overview.test.tsx and web/e2e/05-overview-and-system.spec.ts) |
| FR-MD-11 | folio/marketdata/fallback.py, registry.py, prices.py (is_stale) | tests/integration/test_marketdata_fallback.py, test_marketdata_prices.py | done |
| FR-MD-02 | folio/marketdata/exchanges.py (calendars, job times), folio/jobs/market.py eod_job | tests/unit/test_exchanges.py, tests/integration/test_jobs_market.py | done |
| FR-MD-03 | folio/jobs/market.py backfill_job, queued by POST /instruments, handled by the job-request poller | tests/integration/test_jobs_market.py, test_instruments_api.py, test_scheduler.py | done |
| FR-MD-04 | folio/marketdata/prices.py (gaps, overrides), gap_job | tests/integration/test_marketdata_prices.py, test_jobs_market.py | done |
| FR-MD-06 | folio/marketdata/fx.py, ecb.py | tests/integration/test_marketdata_fx.py | done |
| FR-MD-07 | folio/marketdata/corporate_actions.py, folio/api/routers/corporate_actions.py, ledger_service.confirm_draft, jobs actions_job | tests/integration/test_corporate_actions.py (1:4 split quadruples quantity and keeps cost; dividend drafts) | done (web Insights page: web/src/overview.test.tsx) |
| FR-TX-01 | folio/ledger_service.py, folio/api/routers/transactions.py, web TransactionForm and Transactions page | tests/integration/test_transactions_api.py, web/src/transaction-form.test.tsx, web/e2e/03-transactions.spec.ts | done |
| FR-TX-02 | folio/ledger_service.py (ECB prefill, override), fx-prefill endpoint, web/src/lib/decimal.ts (exact reciprocal of the broker rate) | tests/integration/test_transactions_api.py, web/src/lib/decimal.test.ts, web/src/transaction-form.test.tsx | done |
| FR-TX-05 | folio/positions.py, folio/api/routers/positions.py, web PositionDetail and Holdings | tests/integration/test_positions_api.py, web/src/position-detail.test.tsx, web/src/holdings.test.tsx, web/e2e/02-instruments.spec.ts | done |
| FR-TX-06 | folio/ledger_service.py (rebuild, snapshot requests), folio/jobs/portfolio.py | tests/integration/test_transactions_api.py, test_portfolio.py (a backdated buy changes historical snapshots) | done |
| FR-TX-07 | folio/imports/, folio/api/routers/imports.py, web ImportWizard | tests/integration/test_imports_api.py (fictional Dutch and English Degiro-shaped exports, comma decimals, re-import adds 0 rows, undo), web/src/import-wizard.test.tsx, web/e2e/04-csv-import.spec.ts (import, re-import adds nothing, undo) | done |
| FR-PF-01 | folio/analytics/valuation.py, folio/portfolio.py, folio/api/routers/portfolio.py (summary) | tests/unit/analytics/test_valuation.py, tests/integration/test_portfolio.py (hand-computed periods) | done (web Home: web/src/overview.test.tsx, web/e2e/05-overview-and-system.spec.ts, hand-computed total 408,00) |
| FR-PF-10 | folio/portfolio.py (save_snapshots, lock_closed_years), folio/jobs/portfolio.py | tests/integration/test_portfolio.py (idempotent re-run; 1 January flagged and locked) | done |
| FR-SY-06 | folio/backup.py (VACUUM INTO, integrity check, 14 daily + 8 weekly, extra folder), jobs/scheduler.py (03:00) | tests/integration/test_backup.py, test_scheduler.py | done |
| FR-SY-07 (CLI restore) | folio/backup.py restore_backup, folio/cli.py restore | tests/integration/test_backup.py (restore recreates identical positions), test_demo_cli.py | done |
| FR-SY-08 | folio/audit; instruments, transactions, accounts, prices, settings audited | tests/integration/test_settings.py, test_instruments_api.py, test_transactions_api.py | done (audit viewer with before and after: web/src/overview.test.tsx, web/e2e/05-overview-and-system.spec.ts) |
| NFR-02 | UTC storage (UTCDateTime), exchange-local trading dates (Date columns), migration 0002 | tests/integration/test_schema.py, tests/integration/test_scheduler.py, tests/unit/test_exchanges.py (jobs run at close + 2 h in exchange time) | done |
| FR-PF-03 | folio/analytics/returns.py (TWR, XIRR), ADR 0014 | tests/unit/analytics/test_returns.py (golden cases, reference spreadsheet within 0.01 pp, TWR independent of flow timing) | in progress (pure maths done; API and UI pending) |
| FR-PF-04 | folio/analytics/allocation.py (allocate, drift) | tests/unit/analytics/test_attribution_allocation_series.py | in progress (pure maths done; API and UI pending) |
| FR-PF-06 | folio/analytics/risk.py | tests/unit/analytics/test_risk.py (hand-worked volatility, drawdown, beta, correlation, gold vs equities) | in progress (pure maths done; API and UI pending) |
| FR-PF-07 | folio/analytics/attribution.py | tests/unit/analytics/test_attribution_allocation_series.py (contributions sum exactly) | in progress (pure maths done; API and UI pending) |
| FR-INS-04 | folio/db/models_analytics.py (Sleeve), Instrument region, sector, sleeve_id, migration 0004 | tests/integration/test_schema.py | in progress (schema done; API and UI pending) |
| FR-INS-05 | folio/db/models_analytics.py (Watchlist, WatchlistItem); tracked_listings already prices every active instrument | tests/integration/test_schema.py | in progress (schema done; API and UI pending) |
