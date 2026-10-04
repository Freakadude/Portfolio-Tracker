"""Reading a broker's CSV export: text encoding, delimiter, headers and rows.

Exports vary: UTF-8 with or without a byte-order mark, Windows-1252, comma or semicolon or tab
separated, and (Degiro is an example) several columns with the same name or no name at all.
Columns are therefore addressed by position; labels are only for display.
"""

from __future__ import annotations

import codecs
import csv
import io
from dataclasses import dataclass

MAX_BYTES = 5 * 1024 * 1024
_ENCODINGS = ("utf-8", "cp1252")
_DELIMITERS = (",", ";", "\t")


class ParseError(ValueError):
    """The file cannot be read as a table; the message is for the owner."""


@dataclass(frozen=True)
class ParsedFile:
    encoding: str
    delimiter: str
    headers: list[str]  # as written in the file (may repeat or be empty)
    labels: list[str]  # unique display names, one per column
    rows: list[list[str]]  # data rows, cells stripped
    row_numbers: list[int]  # 1-based line numbers in the file, header being row 1


def decode(data: bytes) -> tuple[str, str]:
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig"), "utf-8-sig"
    for encoding in _ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ParseError("The file is not text in a known encoding (UTF-8 or Windows-1252).")


def sniff_delimiter(text: str) -> str:
    first = next((line for line in text.splitlines() if line.strip()), "")
    counts = {d: first.count(d) for d in _DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ","


def unique_labels(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    labels: list[str] = []
    for index, header in enumerate(headers):
        name = header.strip() or f"(column {index + 1})"
        seen[name] = seen.get(name, 0) + 1
        labels.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return labels


def parse_csv(data: bytes) -> ParsedFile:
    if not data.strip():
        raise ParseError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise ParseError("The file is larger than 5 MB. Export a shorter period.")
    text, encoding = decode(data)
    delimiter = sniff_delimiter(text)
    table = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    numbered = [(n, row) for n, row in enumerate(table, start=1) if any(c.strip() for c in row)]
    if len(numbered) < 2:
        raise ParseError("The file needs a header row and at least one data row.")
    _, header_row = numbered[0]
    width = len(header_row)
    rows, numbers = [], []
    for number, row in numbered[1:]:
        cells = [c.strip() for c in row]
        rows.append((cells + [""] * width)[: max(width, len(cells))])
        numbers.append(number)
    headers = [h.strip() for h in header_row]
    return ParsedFile(encoding, delimiter, headers, unique_labels(headers), rows, numbers)
