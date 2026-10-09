# ADR 0052: Nothing the owner reads shows more than two decimals

Status: accepted (2026-10-09). New scope, asked for by the owner: "for any numerical value displayed in the app, regardless of how calculations use the number in the backend, only up to 2 decimal points".

## Context
The server calculates and stores money and quantities exactly (ADR 0014) and sends them as strings. Most screens already formatted them to two decimals, but an audit found places that did not: unit prices shown with four decimals, units with up to six, raw server strings printed as they came (order prices, delayed prices, bands, targets, alert levels, macro values), AI run costs with four or five decimals, and backend-written sentences (price alerts, rule texts, corporate-action notes, error messages) that used the full stored precision.

## Decision
- **Reading is limited, typing and exporting are not.** Everything displayed shows at most two decimals. Fields you type into keep the exact stored value, so editing and saving never rounds a price; CSV and JSON exports, the tax-support download and "copy for a spreadsheet" keep full precision; the System page's raw agent-run trace stays exact because it is the audit record.
- **One choke point on the web.** `formatEur`, `formatNumber` and `formatPercent` clamp the number of decimals they are asked for to two, and `formatQuantity` allows at most two (whole numbers stay whole). Prices and amounts show two decimals; units, percentage points, targets and bands drop trailing zeros ("60%", "± 5 pp"). An amount above zero that rounds to nothing (the cost of one AI call) reads "< 0.01" rather than "0.00". `roundNumbersIn` rounds the long numbers inside a text for display, which the "data it used" lists under AI answers use.
- **A test keeps it so.** `web/src/display-rule.test.ts` scans the web source for formatter calls asking for more than two decimals, `toFixed` or `maximumFractionDigits` above two, and server fields printed without a formatter.
- **One choke point on the server.** `folio/display.py` (`two`, `small`) is how sentences the server writes for the owner (inbox messages, rule and review texts, notes, errors, job logs) write a number. Stored values, payloads and API fields are untouched.
- **AI text.** The prompts for the system rules, the answer to a question and the recommendation text now ask for at most two decimals, rounded half up. The code gate already accepts a figure rounded to the digits it shows (`unsupported_numbers`), so a correctly rounded figure passes and a wrongly rounded one (6.5 for 6.4312) is refused; scenario 11 of the evaluation set records both. The investigation step still sees and copies exact tool results; only the text the owner reads is rounded.

## Consequences
Prompt versions are 2 for `system`, `ask_answer` and `compose`. A foreign-exchange rate shown as text reads with two decimals (the exact rate is still what is used and what the field holds). Where a price or rate needs more digits than two to be told apart from another, the owner reads it in the field or the export.
