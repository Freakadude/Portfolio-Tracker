# ADR 0035: Outcome tracking compares price only, and scores only two action types

Status: accepted (2026-10-06). Covers FR-AG-06.

## Context
The spec asks for outcomes at +7, +30 and +90 days and a track record with a hit rate by action type. A recommendation can be a contribution, a trim, a hold, a watch item, a thesis review, a hedge check, a rebalance or information. Only some of these say which way a price should go.

## Decision
- A recommendation stores the last close of each subject when it is made (`price_at_creation`). A daily job (23:30 local, after the closes) compares it with the close on the horizon day, or the last close in the five days before it. A horizon whose price is not there waits; after 14 days past the horizon it is closed as "no price" rather than left open forever. Nothing is interpolated or guessed.
- Only `direct_contribution` (hit when the price is at or above where it was) and `trim` (hit when at or below) are scored. Every other action type is measured, so its price change is shown, but never counted as a hit or a miss: there is no honest direction to judge it by.
- Several subjects are averaged. The comparison is the price in the trading currency, not a euro result: it judges the call, not what the owner did with it. Refused recommendations are not tracked.
- The track record shows how many recommendations each number rests on, and the page says that a personal portfolio produces small samples.
- The pure arithmetic is in `folio/agent/outcomes.py` (in the coverage gate); the database part is `folio/agent/trackrecord.py`.

## Consequences
The hit rate is a rough check on the agent, not proof of skill; a trim can "miss" because the price kept rising while the portfolio was still better balanced. Dividends are not added to the price (the close is not adjusted), so the comparison slightly favours trims on dividend payers. Both are acceptable for a rough check and are said in the page's note.
