"""What kind of file a holdings download is, and Excel workbooks read into plain tables (FR-MD-09).

The kind is decided by the file's first bytes, never by its name: an issuer's download link often
has no extension. Every reader here ends in the same thing, a list of rows of text, so the finding
of the header, the matching of the columns and the checks of the weights stay in `parse.py`.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Literal

from folio.imports.parse import ParseError

HOLDINGS_MAX_BYTES = 10 * 1024 * 1024  # workbooks and PDFs are larger than a CSV of the same list
MAX_UNPACKED_BYTES = 100 * 1024 * 1024  # what a workbook may unpack to (a zip bomb stops here)
MAX_SHEET_ROWS = 50_000
MAX_PDF_PAGES = 60

FileKind = Literal["xlsx", "pdf", "xls", "csv"]
Table = list[list[str]]

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # the old binary Excel format (.xls)


def detect_kind(data: bytes) -> FileKind:
    head = data[:8]
    if head.startswith(b"PK\x03\x04"):
        return "xlsx"
    if data[:1024].lstrip().startswith(b"%PDF-"):
        return "pdf"
    if head == _OLE2:
        return "xls"
    return "csv"


def _text(value: object) -> str:
    """A cell as text. Numbers keep the digits they were typed with (7.12 stays 7.12)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        try:
            return format(Decimal(repr(value)), "f")
        except InvalidOperation:
            return str(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def read_workbook(data: bytes) -> dict[str, Table]:
    """Every visible sheet of an .xlsx workbook as rows of text, empty rows left out. Only the
    values Excel last stored are read: no formula is evaluated and no macro is run."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            unpacked = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise ParseError("The file is not a readable Excel workbook (.xlsx).") from exc
    if "xl/workbook.xml" not in names:
        raise ParseError("That file is a zip archive, not an Excel workbook (.xlsx).")
    if unpacked > MAX_UNPACKED_BYTES:
        raise ParseError("The workbook is too large when unpacked (over 100 MB).")

    from openpyxl import load_workbook  # imported when needed: the CSV path never loads it

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many kinds for a damaged file
        raise ParseError("The Excel workbook could not be read. Is it damaged?") from exc
    tables: dict[str, Table] = {}
    try:
        for sheet in workbook.worksheets:
            if sheet.sheet_state != "visible":
                continue
            sheet.reset_dimensions()  # some issuers' files state a one-cell size
            rows: Table = []
            for row in sheet.iter_rows(values_only=True, max_row=MAX_SHEET_ROWS):
                cells = [_text(v) for v in row]
                if any(cells):
                    rows.append(cells)
            if rows:
                tables[sheet.title] = rows
    finally:
        workbook.close()
    if not tables:
        raise ParseError("The workbook has no sheet with any content.")
    return tables


_DATE_LINE = re.compile(r"as of|as at|holdings date|peildatum|\bstand\b", re.IGNORECASE)


def _cell_text(value: object) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def read_pdf(data: bytes) -> Table:
    """The rows of the tables in a text PDF, pages joined. Tables with ruling lines are read by
    their lines; where a page has none, by the alignment of the text. A line of text that states
    a date ("Holdings as of ...") is kept above the table so the date can be found. A scanned
    PDF has no text to read and is refused."""
    import pdfplumber  # imported when needed: only an uploaded PDF loads it

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdfminer raises many kinds for a damaged file
        raise ParseError("The PDF could not be read. Is it damaged or password protected?") from exc
    dates: Table = []
    rows: Table = []
    saw_text = False
    with pdf:
        for page in pdf.pages[:MAX_PDF_PAGES]:
            try:
                text = page.extract_text() or ""
                if text.strip():
                    saw_text = True
                dates += [[line.strip()] for line in text.splitlines() if _DATE_LINE.search(line)]
                tables = page.extract_tables()
                if not any(any(any(c for c in row) for row in t) for t in tables):
                    tables = page.extract_tables(
                        {
                            "vertical_strategy": "text",
                            "horizontal_strategy": "text",
                            "min_words_vertical": 2,  # a last page may hold a header and one row
                        }
                    )
            except Exception as exc:
                raise ParseError("A page of the PDF could not be read.") from exc
            for table in tables:
                for row in table:
                    cells = [_cell_text(c) for c in row]
                    if any(cells):
                        rows.append(cells)
    if not saw_text:
        raise ParseError(
            "This PDF has no readable text (it may be a scan). Use the issuer's Excel or CSV "
            "download instead."
        )
    if not rows:
        raise ParseError(
            "No table was found in this PDF. Use the issuer's Excel or CSV download instead."
        )
    return dates[:5] + rows
