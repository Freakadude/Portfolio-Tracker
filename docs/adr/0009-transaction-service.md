# ADR 0009: Transaction service

Status: accepted (2026-10-04)

## Decisions
- **Derived tables are rebuilt per account, not per instrument.** After every create, edit or delete the whole account is replayed through the pure domain code and its lots, lot matches and positions are replaced. Account-level figures such as net contributions depend on every instrument, a personal ledger has at most thousands of rows, and a single code path is easier to prove correct than incremental updates. Rebuilding twice gives identical rows (invariant 5, tested).
- **A rejected change leaves nothing behind.** The rebuild runs before the audit row and snapshot request are written, and a failure rolls the whole database transaction back. This covers creating an oversell, raising a sell, shrinking a buy that a later sell relies on, and deleting such a buy (invariant 3).
- **`net_amount_eur` means two things, by type.** For income, costs, deposits and withdrawals it is the EUR amount the owner enters. For buys and sells it is the computed cash effect in EUR (negative for a buy, including fees and taxes), so it can be compared with the broker statement. For a transfer in it is the carried-over cost basis (optional).
- **FX rates.** The rate on each transaction is stored: the owner's value if given, otherwise the ECB rate prefilled for the trade date. Fees and taxes carry their own currency and rate. When a transaction's date is edited, a stored rate that equals the ECB prefill for the old date is refreshed for the new date; a rate that differs was overridden with the broker's figure and is kept. Changing the currency always resets the rate.
- **Transactions have a status.** `posted` rows feed the ledger; `draft` rows (dividends proposed from corporate actions) do not, until the owner confirms them.
- **Snapshots are redone by the worker.** Every ledger change queues a `snapshots` job request from the earliest affected date (FR-TX-06).
- **Cost-basis method is per account.** Switching it recomputes every derived number, is audited, and queues a snapshot rebuild from the first transaction.

## Consequences
The API stays small and every ledger rule lives in `folio/domain` and `folio/ledger_service.py`. If an account ever reaches hundreds of thousands of rows, an incremental rebuild per instrument can replace the full replay without changing the interface.
