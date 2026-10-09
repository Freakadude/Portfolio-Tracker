# ADR 0051: Price changes and a refresh-price day on the price chart widget

Status: accepted (2026-10-09). Extends FR-DB-03 and uses the quotes of FR-MD-05. New scope, asked for by the owner.

## Context
The price chart widget drew daily closes only, so its "1 day" timeframe showed one or two points. The owner wanted to see just the price changes (day over day for longer timeframes, refresh over refresh for one day), a timeframe chosen in the widget's settings (which already exists as "Period", including "follow the dashboard"), and reported that the chart in the settings preview seemed to zoom or scroll for ever.

## Decision
- **"Show" lists what is drawn.** `overlays` gains `price` (the line or the candles), `changes` (bars of the percent change from one point to the next) and `since_start` (a line of the percent change against the start of the timeframe). The price is drawn if it is ticked or if no change view is ticked, so a chart is never blank, and leaving it out gives "just the price changes". Averages and trade markers belong to the price and are left out with it. Each change view has its own pane and axis (percent), never sharing one with the price.
- **Changes are computed on the points sent**, with Decimal, as strings with four places. Up to 800 points (about three years of days) every point is a day, so the bars are daily changes. A longer timeframe is thinned for the chart as before, and then each bar spans the days between two drawn points. The first change is taken against the last close before the window.
- **One day uses the quotes.** For the period "1D" (set on the widget or followed from the dashboard) the widget takes the latest session on record for the listing: the quotes of its exchange-local date, in order, in exchange-local clock time (`exchanges.local_time`), against the previous close. The line is drawn from them, candles are not offered (a quote has no open, high or low), and averages, volume and trades are left out. Quotes exist only for what is held or on a watchlist and only while the exchange is open, and are kept for `quotes_days` (7); without any, the widget says so instead of drawing one point.
- **Existing widgets keep showing their price.** Migration 0014 adds `price` to the `overlays` of stored price charts (their price used to be implied). Downgrading removes it and the two change views.
- **The preview no longer grows.** `TimeChart` sized its drawing area to its box (`autoSize`) while the box sized itself to the drawing: in the settings preview, whose height was open, each resize made the next one bigger. The chart now sits out of the layout (`absolute inset-0`) in a box with a minimum height, and the preview of a chart widget is given a fixed height. A browser test checks that the preview keeps its height.

## Consequences
The widget data has new optional keys (`intraday`, `session_date`, `previous_close`, `show_price`, `changes`, `since_start`); nothing else about the API changes. The chart component takes a pane, a value format and a bar kind per series, and numeric times for intraday charts, which other charts can use later.
