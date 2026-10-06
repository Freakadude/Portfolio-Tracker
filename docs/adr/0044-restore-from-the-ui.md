# ADR 0044: A restore is staged by the app and applied at the next start

Status: accepted (2026-10-06). Covers FR-SY-07 (the UI part; the CLI restore was made in Phase 1).

## Context
The CLI restore swaps the database file while the web and worker containers are stopped. The UI has to do it from inside the running web process, which holds the database open, as does the worker.

## Decision
- The web app never swaps the file under itself. `POST /system/restore` verifies the chosen backup (`verify_backup`: opens, integrity check, is a Folio database), copies it beside the database as `folio.db.restore-pending`, writes the audit row, answers `202`, and then asks the process to stop (`SIGTERM` after the response is out). The stack's `restart: unless-stopped` starts it again.
- On start, `folio web` calls `restore.apply_pending` before it migrates or opens anything: the existing `restore_backup` takes a `pre-restore` copy of the current database, swaps the staged file in, removes the WAL files and migrates the restored database forward, and the outcome (success, the safety copy's name, or the error) is written to `folio.db.restore-result.json`. A staged file that fails is renamed `.failed`, never applied twice, and the database is left as it was.
- The worker watches the result file's modification time (every 15 seconds) and exits when it changes, so Docker restarts it on the restored database; until then it may write to the old file, which the pre-restore copy has already captured.
- Safety: the typed word RESTORE is required, names are matched against the exact pattern the app writes (no path can leave the backup folder), uploads are capped at 512 MB and verified before they are kept, and downloads leave out the encrypted API keys unless asked (`stripped_copy`), so a copy that leaves the server does not carry them.
- Nothing in the UI path touches the database file while the app has it open; the swap happens in a process that has not opened it yet. That is also why the tests can run it on Windows: they close every connection first, as a stopped app has.

## Consequences
A restore takes a restart (about a minute) and signs the owner out, because sessions are part of the restored database. A backup made without the API keys brings no keys back, which the confirmation says. Without Docker restart policy (a bare `uv run`), the process just stops and must be started again, as the docs say.
