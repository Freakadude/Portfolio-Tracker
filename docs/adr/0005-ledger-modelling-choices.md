# ADR 0005: Ledger modelling choices

Status: accepted (2026-10-04)

## Context
Phase 1 implements the ledger (spec sections 5 and 7). A few details the spec leaves open had to be fixed so the numbers are reproducible and match a broker statement.

## Decisions
- **Average cost uses one pooled lot per instrument.** Every buy merges into the pool; a sell consumes at the pooled average and records one match against the pool. FIFO keeps one lot per buy. This keeps quantities exact: splitting a sell proportionally across many lots would produce fractional units even when only whole units are traded.
- **Splitting a cost across lots is quantised to 12 decimal places, never to cents.** The consumed part is rounded and the remainder is computed by subtraction, so the parts always add up exactly to the whole. Sale proceeds are allocated across matches the same way. Rounding to cents happens only for display (half-even).
- **Trade costs.** On a buy, fees and taxes are added to the cost basis; on a sell they are deducted from the proceeds. Standalone `fee` and `tax` transactions and dividend withholding tax are tracked separately and enter total return only.
- **Net contributions while cash tracking is off** (owner decision Q7) means money put in from outside: buy cost including fees, minus net sale proceeds, plus transfer-in cost, minus transfer-out cost, plus deposits, minus withdrawals. Total P&L = market value - net contributions + income - standalone fees - taxes, which is the spec's total-return formula. Total P&L percent is over net contributions.
- **Same-day ordering.** Within a trade date, events replay as: splits, then acquisitions (buys, transfers in), then disposals (sells, transfers out), then everything else, then by id. Broker exports list the newest trade first, so a sell can have a lower id than the buy it depends on. Trades on a split's ex-date are treated as post-split.
- **Transfers** carry cost basis without realizing P&L; a transfer-out records matches whose proceeds equal their cost.
- **Native-currency metrics.** Each lot also tracks the gross price paid in the trading currency (fees excluded), so unrealized P&L can be shown in the trading currency next to EUR.
- **Callers convert to EUR.** The domain takes `fees_eur` and `taxes_eur`, already converted with the rate the owner confirmed (FR-TX-02), and a `fx_rate` for the trade price.

## Consequences
Property tests pin invariants 1-5 for both methods; golden YAML scenarios pin hand-computed results. Changing any of these rules changes reported P&L, so it needs a new ADR and updated golden fixtures.
