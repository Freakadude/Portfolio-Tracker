# ADR 0045: ETF holdings files can be Excel workbooks (and PDFs), read by code into the same table

Status: accepted (2026-10-06). Covers FR-MD-09.

## Context
Look-through needs an ETF's full list of holdings. The sources that are free and complete are the issuers' own downloads, and they come as CSV, Excel workbooks (several sheets, columns in any order) or PDF. justETF shows only the top ten and its terms discourage automated queries, and EODHD's free plan has no fund holdings. Folio read only CSV.

## Decision
- The reader already ends in one shape, rows of text; header finding, column matching by name, the preview with corrections and the checks (weights add up, cash and derivatives left out) work on that. New formats only add ways to produce the table.
- The kind of file is decided by its first bytes (`PK` with `xl/workbook.xml`, `%PDF-`, the old OLE2 `.xls` signature), never by its name: an issuer's download address often has none. The old `.xls` gets a message to save it as `.xlsx` or CSV rather than a second library for a format issuers have mostly left.
- Excel is read with `openpyxl` (pure Python, one small dependency `et-xmlfile`): read-only, last stored values only, so no formula is evaluated and no macro run. Before reading, the unpacked size is checked (limit 100 MB, against a zip bomb) and at most 50,000 rows per sheet are read. Numbers are turned into text through the shortest float form, so 7.12 stays 7.12 (they become `Decimal` later, never floats in money or weights).
- A workbook is cut into one table per visible sheet. Each is scored by whether it has a header with name and weight columns and how many rows below it have a weight; the best is suggested and the preview offers the others (the columns are suggested again per sheet). The sheet is part of the saved column choice.
- The size limit for a holdings file rises from 5 to 10 MB; a snapshot's `source` stays `csv` for any uploaded file (it means "uploaded"; the file name is stored), so no migration.
- PDF (next step) uses `pdfplumber`, best effort on text PDFs; a scanned PDF is refused with a message.

## Consequences
One more runtime dependency for Excel (plus `types-openpyxl` for the type check). Real issuer workbooks will have layouts the test workbooks do not; the preview's sheet and column choices are the fallback, and the owner gate asks for one real file of each type.
