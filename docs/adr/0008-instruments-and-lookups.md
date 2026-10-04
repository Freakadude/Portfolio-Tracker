# ADR 0008: Interactive lookups in the web process; instrument lifecycle

Status: accepted (2026-10-04)

## Context
The spec says every provider call leaves from the worker so rate limits and budgets live in one place (section 4). Resolving an ISIN while the owner waits in the add-instrument dialog cannot sensibly wait for the worker's 5-second `job_request` polling, and a job would need a way to hand the answer back.

## Decisions
- **Interactive lookups run in the web process** (resolving an ISIN). The call budget is stored in the database (`provider_call`) and charged with one conditional UPDATE, so the web process and the worker share one budget and cannot exceed it together. Everything else that fetches data (closes, FX, splits, backfills) still runs in the worker; adding an instrument queues a `backfill` job request.
- **Two connections, one writer.** SQLite allows a single writer. Because each provider call is charged through its own connection, a request or job must not hold an open write transaction when it makes a call. The auth dependency now commits the session's "last seen" update immediately, and the FX catch-up fetches from all currencies before writing any rows. A regression test (`test_fx_job_with_two_currencies_does_not_lock_on_the_call_counter`) failed with "database is locked" before the change.
- **Deleting an instrument is a soft delete**, refused while any live transaction uses it (the error lists them). Prices and the listing stay, so adding the same ISIN again restores the instrument with its history instead of failing on the unique ISIN. Archiving is the lighter alternative and hides an instrument from the default list and from price fetching.
- **Provider symbols are built on the server** from the exchange table; the client only picks the exchange, ticker and currency.
- **Pence-quoted London listings are marked unusable** in the resolver until currency scaling exists.

## Consequences
The web container needs outbound access to the providers, like the worker. Instrument edits, creation, restore and deletion are all audited with old and new values.
