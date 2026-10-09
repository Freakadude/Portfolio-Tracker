# ADR 0058: Copying a widget, and filter bars a dashboard can do without

Status: accepted (2026-10-09). Extends FR-DB-02 and FR-DB-03; new scope, asked for by the owner.

## Context
A dashboard could be duplicated as a whole, but a single widget could not. And every dashboard showed the timeframe buttons, the account select and the row of instrument types and holdings, though a dashboard of notes or of one instrument's chart does not need them.

## Decision
- **A widget copy is an ordinary new widget.** In edit mode a "Duplicate" button adds a widget of the same type with a copy of the settings and the same size, under the lowest widget; nothing links it to the original afterwards. A widget with a title of its own gets " (copy)" added to it so the two can be told apart. This uses the existing "add a widget" request (which already takes a size), so there is no new endpoint and the limit on widgets per dashboard applies as before.
- **Two filter bars can be removed per dashboard:** the timeframe (the period buttons and the custom range), and the account select together with the type and holdings row. In edit mode each shows a "Remove" button, and a removed bar leaves a dashed strip with "Add it back". Which bars are removed is saved with the dashboard in its filters (`hidden`); duplicating, exporting and importing a dashboard keep it.
- **A filter that cannot be seen does not stay on.** Removing the account and instruments bar also clears the account, type and holdings filters. Removing the timeframe bar keeps the period the dashboard had, so widgets set to follow the dashboard keep a defined timeframe (the strip says which); a widget can always be given its own period in its settings.

## Consequences
A dashboard without the bars shows no filter row outside edit mode. The saved `hidden` list is not sent with the widgets' data requests, which build their own list of filter fields.
