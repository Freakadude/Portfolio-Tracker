# Traceability

Requirement ID → module → test → status (`todo`, `in progress`, `done`).

## Phase 0 — Foundations

| ID | Module | Test | Status |
| --- | --- | --- | --- |
| FR-SY-01 | folio/api/setup | tests/integration/test_setup.py | todo |
| FR-SY-02 | folio/api/auth, folio/security | tests/integration/test_auth.py | todo |
| FR-SY-05 | folio/security/secrets | tests/integration/test_secrets.py | todo |
| FR-SY-09 (shell) | folio/api/settings | tests/integration/test_settings.py | todo |
| NFR-07 | folio/api/app, docker/, docker-compose.yml | tests/integration/test_security_headers.py | todo |
| NFR-09 | folio/logging, folio/api/health | tests/integration/test_health.py, test_logging.py | todo |
| NFR-10 | CI, pre-commit, pyproject | CI workflow | todo |
| NFR-01 (groundwork) | folio/db/types | tests/unit/test_decimal_type.py | todo |
