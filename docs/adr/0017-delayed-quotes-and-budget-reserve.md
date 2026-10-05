# ADR 0017: Delayed quotes keep the nightly closes' budget; the ECB deposit rate is the risk-free rate

Status: accepted (2026-10-05)

## Decisions
- **Quotes are an extra, closes are the record.** Every 15 minutes the worker asks for quotes of held listings whose exchange is open at that moment (the exchange calendar knows holidays, early closes and each exchange's hours). Quotes are stored in `quote` (pruned after the retention period, default 7 days) and shown beside a position's last close with the label "delayed" and the time. Valuation, snapshots and every analytics figure stay end-of-day, so a half-finished trading day never changes a return.
- **Budget reserve.** A provider may be used for quotes only while, after the calls the request needs, at least a reserve remains of its daily budget: one call per tracked listing for the nightly closes plus a margin of five for a retry or a gap repair. When the budget is nearly spent, quotes pause; the nightly closes never do. A provider without a daily limit (Yahoo) is always eligible, and the next provider in priority order is tried when one is held back. The scheduler skips the run entirely, without a run record, when no held listing is on an open market.
- **Deposit facility rate.** The ECB's key rate (dataset FM, series D.U2.EUR.4F.KR.DFR.LEV, percent, one value per day) is fetched with the exchange rates by the daily FX job and stored in `macro_series` and `macro_point`, the tables the FRED indicators join in Phase 3. The Sharpe ratio uses the rate in force at the end of the window; Settings, Analytics lets the owner use a fixed percentage instead, which is also the fallback while the series is empty. A failed fetch fails the FX job's run (visible on the System page) but keeps the exchange rates that were stored.
- **Fetch first, write after.** Calls counted against the daily budget go through their own database connection, so a job must not hold an open write transaction when it makes one. The deposit-rate update therefore fetches before it creates anything, as the FX update already did.
- **Retention.** A nightly job prunes old quotes and the live-update events the browser has read (one day).

## Consequences
With free-tier budgets (EODHD 20 calls a day) quotes will usually be unavailable from EODHD and come from Yahoo, which is the intended order of preference for a no-cost setup. An owner with a paid plan gets them from the primary provider.
