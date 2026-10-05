# ADR 0015: Opt-in cash tracking

Status: accepted (2026-10-05). Amends ADR 0005 for accounts that opt in.

## Decisions
- **Cash is always derived, only sometimes used.** The ledger computes `cash_eur` for every account: deposits, sale proceeds and income (less withholding and fees) add to it; purchases (with their fees and taxes), standalone fees, taxes and withdrawals take from it; transfers and splits do not touch it. It is also the broker balance a monthly check compares against. An account uses it only when `track_cash` is on (default off, owner decision Q7).
- **Net contributions change meaning when cash is tracked.** Without cash, the money put in is what was spent on holdings (buys less sales, ADR 0005). With cash it is what crossed the account's border: deposits less withdrawals, plus holdings transferred in less holdings transferred out (`external_flows_eur`). Buying and selling is then just moving money between cash and holdings.
- **Value includes the cash**, and income and costs are already inside it. A day's total P&L is therefore `value - net contributions` for such an account; adding income and subtracting costs again would count them twice. `DayPoint` keeps income and costs for display and records how much of them is already inside the value (`income_in_cash_eur`, `costs_in_cash_eur`); the P&L and period figures use only the part outside. A portfolio mixing both kinds of account stays consistent.
- **Switching** the flag is audited and queues a snapshot rebuild from the account's first transaction, because every historical value and contribution changes meaning. The UI warns before the switch.
- **A missing deposit shows as negative cash**, never hidden: the owner records the opening deposit (or a transfer) so the balance matches the broker.

## Consequences
Cash-off remains the default and behaves exactly as before; the cash-on path is covered by a hand-worked month whose cash balance, value and P&L equal the cash-off figures for the same trades.
