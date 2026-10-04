# ADR 0013: UI conventions for numbers, charts and strings

Status: accepted (2026-10-04)

## Decisions
- **Money is never computed in the browser.** Amounts arrive as decimal strings and are converted to numbers only to display them (`web/src/lib/format.ts`). Totals, P&L and weights all come from the API.
- **Number format follows the owner's setting** (Settings > General): `€ 1.234,56` or `€1,234.56`, applied everywhere through one hook. Figures use tabular numerals and are right-aligned.
- **Gains and losses carry a sign and an arrow as well as colour**, and are announced as "gain" or "loss" to screen readers. Percentages are fractions from the API shown with two decimals.
- **A missing price is shown as missing.** A position without a close has empty market figures, a "No price" note with the reason on hover, and a warning that it is left out of the totals; a stale close (more than three trading days old) carries a "Stale" badge. The date and source of a close appear on hover.
- **Charts use TradingView Lightweight Charts**, loaded only on the position page (a separate chunk), and every chart can be shown as a data table (NFR-11). Buy and sell markers are snapped to the close on or before the trade, because a marker needs a day that has a price.
- **Strings live in one file per area** (`web/src/i18n/en.*.json`) merged into one namespace, so Dutch can be added as a second set of files. A test fails if the code asks for a key that does not exist or puts a hard-coded sentence in a heading or button.
- **Dialogs use the native `<dialog>` element**, which gives focus handling and Escape for free.
- **Browser tests run in numbered files** (`01-setup-wizard`, `02-instruments`, ...) because they share one fresh database: the wizard creates the owner that later tests sign in as.

## Consequences
Components stay free of money logic and hard-coded text. Adding a chart type means adding its data-table view too.
