# ADR 0034: Edit any posted transaction, with the amount worked out by the server

Status: accepted (2026-10-06). Adds FR-TX-14, requested by the owner after Phase 4.

## Context
Editing existed for most fields (FR-TX-01, FR-TX-06) but only from the Transactions page, with the type and the account locked, and the euro amount of a buy or sell appeared only after saving. The owner wants to correct any stored parameter, imported or typed, from the position page, and to see the amount follow the inputs.

## Decision
- `TransactionChanges` (the PATCH body) gains `type` and `account_id`. When the type changes, the merge starts from the fields every type shares (account, instrument, dates, note) plus what the caller sends, so a price or fee of the old type cannot linger on, say, a dividend. The web form therefore sends the whole row when the type changes and only the changed fields otherwise.
- Moving a transaction to another account rebuilds both accounts, and either rebuild can refuse the change (units never held); a refusal rolls everything back as before.
- The calculated amount comes from a new `POST /transactions/preview-amount` that runs the same `normalize` as saving and writes nothing. The browser does not repeat the arithmetic, so the two cannot differ (the money rules: Decimal end to end, rates as stored or the ECB prefill).
- The position page's history rows get Edit and Delete, opening the existing form in a dialog.
- Imported rows keep `source` and `external_ref`, so the import's duplicate check, which uses the broker reference, still recognises them.
- Not changed: the lot preview of a sale is still shown only when adding, not when editing a sale, because the preview would have to leave the edited row out of the history first.

## Consequences
An edit that changes a past trade rewrites derived data from that date, as FR-TX-06 already required, and the audit log keeps the old and new values, now including type and account. Rows the worker made from corporate actions can be edited like any other; how the worker treats an edited one on a later run was not examined here.
