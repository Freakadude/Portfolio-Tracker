# ADR 0012: Worker schedule, job requests and backups

Status: accepted (2026-10-04)

## Decisions
- **APScheduler 3 with a persistent job store** in the same SQLite file. Jobs are registered by importable name (`folio.jobs.scheduler:run_fx` and so on) and read the worker's context from one module-level runtime, because a persistent store pickles each job's callable and a closure cannot be pickled. Every job is coalesced with one instance at a time and a six-hour misfire grace, so a run missed while the worker was down happens once after it restarts (NFR-05). Restarting replaces jobs by id, so nothing is duplicated.
- **One scheduled job at a time** (a single-thread executor). SQLite has one writer and the nightly jobs are short, so serial execution removes lock contention instead of managing it.
- **Closes are fetched two hours after each exchange closes**, in the exchange's own timezone, on weekdays. The job itself asks the exchange calendar and does nothing on a holiday; exchanges where none of the owner's listings are tracked leave no run record at all.
- **Other schedules** (Amsterdam time): ECB rates 16:30, gap repair 22:00, snapshots 23:00, backup 03:00, splits and dividends Sunday 09:00.
- **Job requests** from the web (a backfill after adding an instrument, snapshots after a ledger edit, "refresh now") are rows in `job_request`, polled every five seconds, handled oldest first. A request that fails is marked failed with the reason and never blocks the queue.
- **Backups** use `VACUUM INTO` on a live database, are verified with `PRAGMA integrity_check` before they count (an unverified copy is deleted), optionally copied to a second folder, and pruned to the 14 newest plus the newest of each of the 8 previous weeks. Pre-migration and pre-restore safety copies are kept separately (the last five of each). A backup keeps stored API keys in their encrypted form; `--no-secrets` removes them for copies that leave the machine.
- **Migrations take a safety copy first**, when an existing database is not yet at the latest schema. Migrations remain forward-only.
- **Restore** verifies the file, keeps the current database as a `pre-restore` copy, swaps the file in, and migrates it forward. It must run with the web and worker stopped; if the file is in use the command says so and changes nothing.
- **`folio seed --demo`** adds a fictional portfolio (hand-priced instruments, invented prices and exchange rates) and refuses when instruments or transactions exist, so it can never mix with real holdings.

## Consequences
A second worker process would double-run jobs; the stack runs exactly one. Backups of a PostgreSQL database are out of scope (use `pg_dump`); the commands say so.
