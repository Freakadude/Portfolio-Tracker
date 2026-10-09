# ADR 0057: A choice for the Dashboards tab, more options on the note, and charts that refit

Status: accepted (2026-10-09). Extends FR-DB-01 and FR-DB-03; new scope, asked for by the owner.

## Context
The Dashboards tab always showed the list of dashboards. The note widget had only a title and a text. And a chart in a widget sometimes started toward the middle of its widget after the owner left the page and came back.

## Decision
- **The Dashboards tab can open a dashboard.** A button on a dashboard ("Open this from the Dashboards tab") saves its id in this browser (`folio.dashboards.tab`); the tab (`/dashboards`) then redirects to it. "All dashboards" goes to the list at `/dashboards/all`, which is the page the list always was. The choice is separate from the dashboard marked default, which stays what Home shows, and it is per browser like the holdings default view (ADR 0054): no server setting, no migration. If the chosen dashboard no longer exists the tab shows the list.
- **The note widget** gets `title_only` (the widget shrinks to its title, as a heading), `title_size` (small to extra large) and `background` (none, blue, green, amber, red, purple, grey). A background is a tint of one of the app's colours mixed into the card colour, not a free colour, so the text keeps its contrast in the light and the dark theme. Stored as widget configuration; no migration.
- **Charts refit when their box changes size.** The dashboard grid measures its width after the first paint, and a widget can be laid out narrower or wider than the chart was first drawn. The chart library then keeps its bar width and the right edge, so a chart that became wider starts toward the middle (reproduced in a browser test: the line began at 56% of the width). `TimeChart` and the position page chart now fit their content again on every size change, until the owner zooms or scrolls the chart themself (`keepFitted`).

## Consequences
A browser test draws a price chart, resizes the page narrower and wider and leaves and returns, and checks the line runs from the left edge to the right edge each time.
