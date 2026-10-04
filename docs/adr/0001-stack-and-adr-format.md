# ADR 0001: Stack and ADR format

Status: accepted (2026-10-04)

## Context
The requirements (spec section 4) fix the stack. Decisions that depart from or refine it are recorded as ADRs in this folder, one short file each: context, decision, consequences.

## Decision
Python 3.12 with uv, FastAPI, SQLAlchemy 2 and Alembic on SQLite (WAL), React 18 with Vite and TypeScript for the UI. Owner confirmed React over htmx (Q11).

Python is pinned to 3.12 through `.python-version` even though newer interpreters are installed locally, so local, CI and container match.

## Consequences
All code targets 3.12. Dependency versions are pinned in `uv.lock` and `package-lock.json`.
