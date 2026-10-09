# ADR 0054: The default view of the Positions tab is kept in the browser

Status: accepted (2026-10-09). Concerns the holdings list (FR-TX-05); new scope, asked for by the owner.

## Context
The Positions tab has an account filter, a switch for closed positions, a grouping (none, account, sleeve, asset class), a "group by ISIN" box and a sort order. Only the ISIN box was remembered; everything else started from the standard view on every visit. The owner asked for a button to save the current view as the default.

## Decision
- "Save as default view" stores the account, closed positions, grouping, ISIN grouping and sort order as one small JSON value in the browser's local storage (`folio.holdings.view`). The tab opens with it; "Back to the standard view" removes it. The button is disabled while the screen already equals the default.
- It is a per-browser convenience like the "group by ISIN" box before it, not a server setting: nothing depends on it, it needs no migration or API, and a view that suits a phone need not be the one for a desktop. A saved view that cannot be read, or an account that has since been deleted, is ignored and the standard view applies.
- With no saved view, the ISIN box is still remembered as before. A saved default decides it when there is one.
- The filter that a chart slice opens (`?group_by=`) is a link, not part of the view, and is never saved.

## Consequences
The default is not shared between devices. If that is wanted later it can move to a server setting without changing the screen.
