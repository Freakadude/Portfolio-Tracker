# ADR 0047: A close is a finished session; the newest quote values the portfolio while the market is open

Status: accepted (2026-10-07). Covers FR-MD-04 and FR-MD-05. Amends ADR 0017 (values were end-of-day only).

## Context
The owner saw "Last close" equal to "Latest price" in the holdings widget, and prices on the Home page that stayed a day old although the 15-minute quote job kept running.
- A provider's daily bar for a session still in progress carries the price so far. "Refresh prices now" stored it as that day's close. The nightly update only asked for days after the newest stored bar, so the wrong close was never corrected, and later quotes were ignored because they had the same date.
- Each provider's quote call stopped at the first symbol it did not know, so one wrong symbol (CEBJ) cost every holding its quote. The run still ended "ok".
- Even stored quotes only filled the "Latest price" column; values, Today and day change used the closes.

## Decision
- **A close is only stored once its session has finished** (`PriceService` given the job clock drops a bar of the exchange-local day whose session is not over). "Last close" is therefore always a real close: yesterday's during the session, today's after it.
- **The nightly update asks again for the five days before the newest bar** in the same single provider call, which repairs a close that was stored too early and takes provider corrections. Overridden bars stay protected.
- **Quotes are fetched per listing; an unknown symbol is skipped** (the other errors still hand the whole request to the next provider, and a provider that knows none of the symbols is skipped). The quote job names the listings it got no quote for, as information, not as an error, so a wrong symbol does not mark every run as failed. The nightly closes keep reporting it as an error.
- **A quote is newer than the close by the exchange's own calendar**, not the UTC date (a New York evening quote belongs to that New York day).
- **While a market is open, the figures follow the newest quote.** Positions are valued at the quote and the day's change is the quote against the last close (`quote_for`). The analytics context takes an opt-in `live` flag that adds one synthetic point per listing at the quote's day; the dashboards, the portfolio summary and the history use it. Snapshots, backtests, reports, tax figures, risk and rule inputs keep using closes only, so nothing saved or reported contains an intraday price. Once the nightly close is stored it replaces the quote.

## Consequences
During the session the Home figures move every 15 minutes (as far as the quote providers and the call budget allow) and settle on the true close afterwards. The live context is cached separately and also keyed on the stored quotes. A listing without a calendar (priced by hand) has no quotes and is unchanged.
