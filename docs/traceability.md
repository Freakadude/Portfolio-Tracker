# Traceability

Requirement ID → module → test → status (`todo`, `in progress`, `done`).

## Phase 0 — Foundations

| ID | Module | Test | Status |
| --- | --- | --- | --- |
| FR-SY-01 | folio/api/routers/setup, web/src/pages/Setup.tsx | tests/integration/test_setup.py, web/e2e/setup-wizard.spec.ts | done |
| FR-SY-02 | folio/api/routers/auth, folio/security | tests/integration/test_auth.py | done |
| FR-SY-05 | folio/security/secrets, redact (done) | tests/integration/test_secrets.py, test_settings.py, test_logging.py | done |
| FR-SY-09 (shell) | folio/api/routers/settings, folio/settings_schema.py, web/src/pages/Settings.tsx | tests/integration/test_settings.py, web/src/app.test.tsx, web/e2e/setup-wizard.spec.ts | done |
| NFR-07 | folio/api/middleware (CSP, CSRF), docker/Dockerfile, docker-compose.yml | tests/integration/test_security_headers.py, test_deploy_config.py; multi-arch image build in CI (passed) | in progress (waiting for first fully green CI run) |
| NFR-09 | folio/logging, folio/api/routers/health (Prometheus /metrics is optional, not built) | tests/integration/test_health.py, test_logging.py | done |
| NFR-10 | .github/workflows/ci.yml, .pre-commit-config.yaml, pyproject.toml, web/eslint.config.js | CI workflow: ruff, mypy, pytest, pip-audit, eslint, vitest, npm audit, e2e, gitleaks | in progress (waiting for first fully green CI run) |
| NFR-01 (groundwork) | folio/db/types | tests/unit/test_decimal_type.py | done |
