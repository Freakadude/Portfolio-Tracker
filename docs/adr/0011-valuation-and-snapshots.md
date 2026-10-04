# ADR 0011: Valuation, period figures and snapshots

Status: accepted (2026-10-04)

## Decisions
- **One valuation code path.** `folio.portfolio.Valuation` loads the ledger, the closes and the ECB rates once and values the portfolio on any day. The summary asks it for two or three days; the snapshot job asks it for thousands. The summary is computed on demand rather than read from stored snapshots, so it can never lag or disagree with the ledger, and it matches the positions API (a test checks both give the same value).
- **Market value** on a day is each holding's quantity at the end of that day times the latest close on or before it, converted with the ECB rate of the close's date. A holding with no close or no rate is counted as *unvalued*: it is left out of the value and reported (`unvalued_positions`), never guessed.
- **Total P&L** = market value - net contributions + income - standalone fees and taxes, over net contributions (ADR 0005). **Period P&L** is the same quantity between two days: value change - money put in + income - costs, over the capital at work (start value plus net flows). The start of a period is the day *before* it begins, so flows on the first day belong to the period. Time-weighted return and XIRR are separate figures (Phase 2).
- **Day change** is the one-day period. It includes income received that day.
- **Snapshots are written for every calendar day** from the first transaction, so weekend deposits and withdrawals are never lost and the chart can show a flat weekend. Each row stores value, net contributions, income, costs, the number of unvalued holdings and the holdings themselves.
- **Idempotent.** Re-running writes identical rows. The nightly run fills everything missing and refreshes the last seven days (late closes and fixes); a run queued by a ledger edit redoes everything from the earliest affected date (FR-TX-06).
- **Peildatum.** The 1 January snapshot is flagged, valued at the last close on or before it, and locked once its year has closed. A locked snapshot is left as filed when the ledger is corrected later; ordinary days are recomputed. Forcing a rewrite requires an explicit option.
- **Cash** is not tracked (Q7): the summary reports it as null.

## Consequences
The nightly job's cost grows with the number of distinct transaction dates times the ledger size (each distinct date is one replay, memoised). That is milliseconds at personal scale; an incremental valuation can replace it later behind the same interface.
