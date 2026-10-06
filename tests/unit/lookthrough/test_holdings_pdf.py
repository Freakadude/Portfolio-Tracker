"""Holdings from text PDFs (FR-MD-09): tables made in the test, ruled and not, over several pages.
The expected holdings and coverage are counted by hand."""

from datetime import date
from decimal import Decimal

import pytest
from fpdf import FPDF

from folio.imports.parse import ParseError
from folio.lookthrough.parse import read_holdings, suggest

D = Decimal
HEADER = ["Name", "ISIN", "Weight (%)"]
PAGE_1 = [["ALPHA TECH INC", "US0000000001", "40.50"], ["BETA BANK PLC", "GB0000000002", "30.00"]]
PAGE_2 = [["CHIP MAKER NV", "NL0000000003", "20.25"]]
PAGE_3 = [["DELTA OIL SA", "FR0000000004", "9.25"]]


def pdf_with_tables(pages: list[list[list[str]]], ruled: bool = True, title: str = "") -> bytes:
    """One table per page, the header repeated on each."""
    pdf = FPDF()
    pdf.set_font("Helvetica", size=10)
    for number, rows in enumerate(pages):
        pdf.add_page()
        if number == 0 and title:
            pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
        if ruled:
            with pdf.table(col_widths=(80, 50, 30)) as table:
                for cells in [HEADER, *rows]:
                    row = table.row()
                    for cell in cells:
                        row.cell(cell)
        else:  # no lines at all: only the alignment of the text says these are columns
            for cells in [HEADER, *rows]:
                for width, cell in zip((80, 50, 30), cells, strict=True):
                    pdf.cell(width, 8, cell)
                pdf.ln(8)
    return bytes(pdf.output())


def holdings(data: bytes) -> list[tuple[str, Decimal]]:
    read = read_holdings(suggest(data))
    return [(c.name, c.weight_pct) for c in read.constituents]


def test_a_ruled_table_over_three_pages_is_one_list_without_repeated_headers() -> None:
    data = pdf_with_tables([PAGE_1, PAGE_2, PAGE_3], title="Holdings as of 02/10/2026")
    file = suggest(data)
    read = read_holdings(file)
    assert [(c.name, c.weight_pct) for c in read.constituents] == [
        ("ALPHA TECH INC", D("40.50")),
        ("BETA BANK PLC", D("30.00")),
        ("CHIP MAKER NV", D("20.25")),
        ("DELTA OIL SA", D("9.25")),
    ]
    assert read.covered_pct == D("100.00") and read.errors == []
    assert read.constituents[2].isin == "NL0000000003"
    assert file.as_of == date(2026, 10, 2)  # the date line above the table
    assert file.sheets == []  # a PDF has no sheets


def test_a_table_without_lines_is_read_by_the_alignment_of_its_text() -> None:
    assert holdings(pdf_with_tables([PAGE_1, PAGE_2], ruled=False)) == [
        ("ALPHA TECH INC", D("40.50")),
        ("BETA BANK PLC", D("30.00")),
        ("CHIP MAKER NV", D("20.25")),
    ]


def test_a_top_ten_factsheet_says_how_little_of_the_fund_it_covers() -> None:
    read = read_holdings(suggest(pdf_with_tables([PAGE_1])))
    assert read.covered_pct == D("70.50")
    assert any("covers 70.5 %" in w for w in read.warnings)


def test_a_pdf_with_text_but_no_holdings_table_is_explained() -> None:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    pdf.add_page()
    pdf.multi_cell(0, 8, "This factsheet describes the fund and its objectives in words only.")
    with pytest.raises(ParseError, match="[Nn]o (header row|table)"):
        suggest(bytes(pdf.output()))


def test_a_pdf_without_any_text_is_taken_for_a_scan() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.line(10, 10, 100, 100)  # a drawing, no text
    with pytest.raises(ParseError, match="no readable text"):
        suggest(bytes(pdf.output()))


def test_a_damaged_pdf_gets_a_plain_message() -> None:
    with pytest.raises(ParseError, match="could not be read"):
        suggest(b"%PDF-1.7\nthis is not a pdf at all")
