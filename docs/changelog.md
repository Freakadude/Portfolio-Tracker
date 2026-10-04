# Changelog

## Unreleased

### Phase 0 — Foundations
- Repo conventions: CLAUDE.md, ADRs, traceability, shared Claude Code permission rules.
- Python 3.12 uv project, ruff/mypy/pytest config, settings, SQLite engine (WAL) and `DecimalText` type with property tests [NFR-01].
- Auth: Argon2id passwords, DB-backed sessions (HttpOnly, SameSite=Strict, Secure over HTTPS, 30-day remember), persisted login throttle (5 failures / 15 min), CSRF double-submit cookie, CSP and security headers, RFC 9457 errors, Alembic migration 0001 [FR-SY-02, NFR-07].
- Encrypted secret store (Fernet, HKDF-derived key), masked display, redacted repr [FR-SY-05].
