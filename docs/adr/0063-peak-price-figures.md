# ADR 0063: Peak price and the figures that follow from it

Status: accepted (2026-10-15). Extends FR-TX-05 (holdings) and FR-DB-03 (key figures); new scope, asked for by the owner.

## Context
The owner wanted to see how far each holding sits below the best price it has had since they bought it: the peak price, how far the last price is below it, what the holding would fetch at the peak, and how far today's value is below that.

## Decision
- **Since the first buy.** The window starts on the first posted buy of the instrument over all accounts. An instrument with no buy has no peak (the figure says so).
- **Peak price** is the highest daily close of the instrument's primary listing from that day, in the trading currency, the same unit as the Price column. A newer price (the delayed quote) above every close counts as the peak; the fall-off is then 0. The day it was reached is kept.
- **Peak price fall-off** is last price / peak - 1, never above 0. The last price is the one the Holdings tab shows (the delayed quote when it is newer than the close).
- **Peak value** is today's value times peak / last price: today's quantity and today's exchange rate, as the owner chose. The rate at the time of the peak is not used. Because the quantity is today's, **peak value fall-off** is numerically the same as the peak price fall-off; it is offered as its own figure as asked, and the Key figure says it is measured on today's holding.
- **Where.** The Holdings tab gets only Peak price, right of Price, sortable, with the day as a hint and the fall-off in small text under it. The Key figure widget gets all four (for one holding, like Latest price) and the holdings table widget gets the price, the fall-off and the value as optional columns. The helper's privacy projection treats the euro peak value like any euro amount.
- **Daily closes only.** Intraday quotes are pruned after a retention period, so the peak is of closes plus the newest quote; a higher price within a past day that never closed there is not known.

## Consequences
No new table or migration: the peak is worked out from stored closes and the ledger on request, one query per holding for the list.
