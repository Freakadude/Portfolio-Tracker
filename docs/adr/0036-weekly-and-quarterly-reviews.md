# ADR 0036: The weekly review is an agent run; the quarterly review is made by code

Status: accepted (2026-10-06). Covers FR-AG-07 and FR-ST-08.

## Context
FR-AG-07 asks for a weekly deep review (digest on Sunday evening) and a quarterly strategy review summary. FR-ST-08 asks for a quarterly prompt with a generated summary of drift history, signals fired and recommendations with their outcomes, which creates an Insights item. The agent already has a `weekly_review` run type with a model setting (Opus) and a digest item.

## Decision
- The weekly review is an ordinary agent run of type `weekly_review`, due once per ISO week on Sunday from `AgentSettings.weekly_review_time` (default 18:00 local). Its trigger is `weekly:<year>-W<week>`, so a restart or a second tick cannot start it twice, and a missed Sunday is not made up on Monday. It passes through the same code gate, budget guard and delivery as every run.
- The quarterly review is built by code, not by a model: the facts are all in the database (weights by day, signals, recommendations and their measured outcomes), a model would only add cost and the risk of an invented number, and the summary then needs no gate. `folio/strategies/review.py` has a pure core (`build_review`, `render`, in the coverage gate) and a thin database side.
- It is posted once per quarter: the inbox item's subject is `review:<year>Q<n>` and posting checks for it first. The job runs on the first morning after a quarter ends and can be run again safely; the page can show any of the last eight quarters, and a finished quarter can be put in the inbox by hand. A quarter that is not over is a preview and cannot be posted, so an early look never blocks the real item.
- Drift is measured on the sleeves of the active strategy as they are now (members and targets of its latest version) against the portfolio's weights on each day, so a strategy edited during the quarter is judged by its current targets, and the review says when a sleeve has no target.

## Consequences
The weekly run costs one Opus run a week (a few cents to tens of cents, inside the budget guard). The quarterly review is free, deterministic and repeatable. If the owner later wants a narrative on top of the numbers, the text can be passed to an agent run as its focus without changing this module.
