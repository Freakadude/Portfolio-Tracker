# ADR 0056: The Price history widget: a chart for each instrument on one time axis

Status: accepted (2026-10-09). Extends FR-DB-03 and uses the quotes of FR-MD-05. New scope, asked for by the owner.

## Context
The price chart widget shows one instrument. The owner wanted a widget to follow the price of one or several instruments over a timeframe chosen like the dashboard's, with the refresh prices of the trading day for 1 day and the closing price of each day for anything longer.

## Decision
- **The plain price, one chart for each instrument.** Prices of different instruments and currencies do not share a scale, so each chosen instrument (up to six) is drawn in its own pane, stacked on one shared time axis; the chart component already has one axis per pane. The owner chose the plain price over percent change; a widget that compares them rebased on one axis remains the performance comparison.
- **One day:** the refresh prices (quotes) of the latest session on record, each as its own point, in the owner's time zone so instruments of different exchanges share one clock. The axis is stretched from the earliest open to the latest close of the chosen instruments' exchanges that day (blank points at the open and the close, so the curve ends where the prices stop). When there is no trading today (weekend, holiday, before the open) the latest session on record is shown and the widget says it is not today. The change is against the close before the session.
- **Any other timeframe:** the daily closes inside the period, one point a day, the last closed price of that day; no refresh price is mixed in. The change runs from the close at the start of the period.
- The timeframe is the widget's Period (the dashboard's choices or "follow the dashboard"); the instruments are chosen in the widget's settings.

## Consequences
Quotes are kept for 7 days and fetched only for what is held or on a watchlist, so a 1-day chart of anything else says there are no refresh prices. No migration: the widget is a new type with its own configuration.
