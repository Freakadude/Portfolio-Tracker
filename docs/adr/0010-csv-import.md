# ADR 0010: CSV import design

Status: accepted (2026-10-04)

## Decisions
- **Columns are addressed by position.** Degiro-style exports repeat header names and leave some empty (the currency columns after each amount). Headers are shown with unique labels, but a mapping stores column indexes. The first guess comes from header aliases (English and Dutch), from unnamed columns that hold currency codes, from number and date samples, and from the file shape (an account statement with only a description column treats it as the transaction type).
- **Buy or sell comes from the quantity's sign or from a type column.** The sign rule matches Degiro's transaction export (sells are negative); a type map handles statements ("Dividend", "Fee"), and listed texts can be skipped. Amounts and fees are read as absolute values.
- **Foreign exchange rates** in the file are either "foreign units per euro" (Degiro) or a euro multiplier; the choice is part of the mapping. Rows in euro ignore the rate column. When the file has no rate, the ECB rate for the trade date is used as for manual entry.
- **Idempotence.** Each row gets a key: a hash of order reference, date, time, ISIN, quantity, price, amount and type, plus a counter for identical rows in one file (two equal partial fills of one order are two trades). The key is stored as `external_ref`; a partial unique index per account refuses duplicates, and a re-import marks those rows as duplicates.
- **Everything is checked before anything is written.** The dry run converts and normalises every row, finds unknown ISINs, flags duplicates, and replays the account's history plus the new rows so a sell larger than the holding becomes an error row (as do later rows that depended on it). Rows are replayed in trade-date order regardless of file order, because exports list the newest trade first.
- **Commit is all or nothing.** By default any error row blocks the commit; "import the valid rows only" is an explicit choice. One database transaction posts the rows, rebuilds the account once, writes one audit entry and one snapshot request, and drops the stored upload.
- **The upload is kept only while it is a preview**, as base64 in the batch record, so the owner can adjust the mapping without uploading again. A committed batch keeps its counts and error report, not the file.
- **Undo** soft-deletes all the batch's transactions and rebuilds; it is refused, with the reason, when later transactions depend on the imported ones. An undone import no longer blocks a re-import.
- **Presets** store the whole mapping, can be saved from the mapping step, replace a preset of the same name, and may be deleted without touching past imports.

## Consequences
Broker-specific presets (FR-TX-08) are just saved mappings built from a sample export. Real exports contain amounts and must never be committed; the fixtures in `tests/fixtures/imports/` are invented.
