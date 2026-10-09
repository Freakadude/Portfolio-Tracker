# ADR 0053: "Latest price" as a key figure, with the day's movement as its chart

Status: accepted (2026-10-09). Extends FR-DB-03 and uses the quotes of FR-MD-05 and the price rule of ADR 0047. New scope, asked for by the owner.

## Context
The key figure widget showed values and returns of the portfolio, an account, a sleeve or an instrument, all built from the analytics context (which is empty until a transaction exists). The owner wanted the plain latest price of a holding as a figure, with a chart of how the price moved over the day.

## Decision
- **A figure that does not need the analytics context.** `latest_price` is answered before the context is built, from the instrument's primary listing, so it works for a holding that is only watched, or not held at all. It needs the scope "One instrument"; any other scope says what to choose.
- **Which price.** The newest refresh price (quote) when it was made on a later exchange-local day than the newest close (`newer_quote`, the rule of ADR 0047), otherwise the newest close; the label says which and when. The value is in the instrument's own currency and is shown with two decimals (ADR 0052).
- **The chart follows the timeframe.** For 1 day (on the widget or followed from the dashboard) it is the refresh prices of the latest session on record, beginning at the close before it, with that close drawn as a dotted line so the ups and downs of the day can be seen, and the change is against that close. For longer timeframes it is the daily closes of the period (with the newest refresh price at the end when it is newer) and the change runs from the close at the start. Without refresh prices there is no day chart; the figure still shows the close and the note says why. The session helpers (`_primary_listing`, `_session`, `_price_window`) are shared with the price chart widget (ADR 0051).
- The figure opens the position page of the holding when clicked.

## Consequences
No migration: the figure is a new value of a string option in the widget's stored configuration. The data of the widget gains `currency`, `instrument_id`, `name`, `intraday` and `baseline` for this figure only.
