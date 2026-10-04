# Traceability

Requirement ID → module → test → status (`todo`, `in progress`, `done`).

## Phase 0 — Foundations

| ID | Module | Test | Status |
| --- | --- | --- | --- |
| FR-SY-01 | folio/api/routers/setup (API done; wizard UI pending) | tests/integration/test_setup.py | in progress |
| FR-SY-02 | folio/api/routers/auth, folio/security | tests/integration/test_auth.py | done |
| FR-SY-05 | folio/security/secrets (store done; API masking and log scrubbing pending) | tests/integration/test_secrets.py | in progress |
| FR-SY-09 (shell) | folio/api/routers/settings, folio/settings_schema.py (API done; UI pending) | tests/integration/test_settings.py | in progress |
| NFR-07 | folio/api/middleware (CSP, CSRF) done; docker/, docker-compose.yml todo | tests/integration/test_security_headers.py | in progress |
| NFR-09 | folio/logging, folio/api/health | tests/integration/test_health.py, test_logging.py | todo |
| NFR-10 | CI, pre-commit, pyproject | CI workflow | todo |
| NFR-01 (groundwork) | folio/db/types | tests/unit/test_decimal_type.py | done |
