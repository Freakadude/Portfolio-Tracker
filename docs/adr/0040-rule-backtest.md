# ADR 0040: Backtesting replays the live rules on prepared history, with the live repeat filter

Status: accepted (2026-10-06). Covers FR-ST-06.

## Context
"Run any rule over history and list when it would have fired." The rules engine takes a `RuleInputs` snapshot of today (sleeve weights, closes, the time-weighted index, macro series) and returns findings; signals then go through a dedup (cooldown, worsening) before they notify.

## Decision
- The backtest builds the same `RuleInputs` for each past day from one analytics context loaded once (`History`): per-day value of each holding, euro closes aligned to the days, closes in the trading currency for price levels, the portfolio index and each sleeve's returns computed once and sliced by window, and the macro series. Evaluating a day is then a pure function of the prepared history, so a three-year range runs in one pass without a query per day. `inputs_on` and `run_backtest` are pure and in the coverage gate (`folio/strategies/*`).
- The live evaluator is used unchanged (`rules.evaluate`), and the findings pass through the live repeat filter in memory (`signals.should_fire`: a condition that stays true fires again after its cooldown or when it has worsened by the rule's step; one that clears is forgotten and fires at once when it returns), with the end of each day as the moment. The list is therefore what the inbox would have shown, not just the days a condition held; both counts are given per rule.
- It judges the version being looked at: the rules, the sleeve members, targets and bands are those of the latest version, applied to the history as stored. A strategy edited since is not reconstructed (each version is immutable, but the portfolio's past under an older version is not the question being asked).
- Days with nothing held (before the first purchase) and days with no close are skipped; an empty portfolio would otherwise be 60 pp off every target.
- Rules that rely on what was not kept for past days are not run and are named with the reason: `stale_data` (how fresh prices were), `contribution_due` and `thesis_review_due` (dates as they stand now), `concentration_limit` (the ETF holdings of each day; only the saved snapshots are known). A rule waiting for numbers (no target, no macro data) shows what it waits for.
- Nothing is stored, no signal is created and nothing is sent; the range is limited to 1,100 days.

## Consequences
The backtest is as good as the stored history: a price gap in the past is a gap in the replay. It answers "would this rule have been noisy?", which is what tuning bands and cooldowns needs, and it deliberately does not claim to say whether acting on the signals would have paid.
