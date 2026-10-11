"""
ingest.py
PDF ingestion: reads an annual report PDF page-by-page and returns a list of
page dicts, each containing the page number, plain text, and any tables
converted to markdown so column headings (e.g. years) stay attached to their numbers.
"""

from __future__ import annotations

import re
import io
from dataclasses import dataclass, field
from typing import Optional

import pymupdf as fitz  # PyMuPDF (fitz alias for compatibility)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PageData:
    pdf_index: int          # 0-based PDF page index
    page_number: int        # printed page number extracted from footer/header (or pdf_index+1)
    text: str               # plain text of the page
    tables_markdown: list[str] = field(default_factory=list)  # each table as markdown
    has_table: bool = False

    @property
    def full_text(self) -> str:
        """Combined plain text + table markdown for indexing."""
        parts = [self.text]
        parts.extend(self.tables_markdown)
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAGE_NUMBER_RE = re.compile(r'(?<!\d)(\d{1,4})(?!\d)')


def _detect_printed_page_number(text: str, pdf_index: int) -> int:
    """
    Try to find a printed page number in the page text.
    Looks for isolated small numbers in the first or last 200 characters.
    Falls back to pdf_index + 1 if nothing reliable is found.
    """
    candidates: list[int] = []
    for region in [text[:200], text[-200:]]:
        for m in _PAGE_NUMBER_RE.finditer(region):
            n = int(m.group(1))
            # Reasonable page numbers: 1..999 and within ±30 of pdf_index
            if 1 <= n <= 999 and abs(n - (pdf_index + 1)) <= 30:
                candidates.append(n)
    if candidates:
        # Prefer numbers closest to the expected pdf page index
        return min(candidates, key=lambda x: abs(x - (pdf_index + 1)))
    return pdf_index + 1


_YEAR_COL_RE = re.compile(r"\b(fy\s*\d{4}|\d{4})\b", re.IGNORECASE)


def _is_year_header(cell: str) -> bool:
    """Return True if the cell text looks like a fiscal year column heading."""
    return bool(_YEAR_COL_RE.search(cell.strip()))


def _table_to_markdown(table: list[list[Optional[str]]]) -> str:
    """
    Convert a pdfplumber table to markdown.

    If the header row contains year-like columns (e.g. '2025', 'FY2025'),
    each data row is annotated as 'Row label | Year: value | Year: value'
    so the LLM can correctly identify which value belongs to which year.
    """
    if not table:
        return ""

    # Normalise cells
    rows: list[list[str]] = []
    for row in table:
        rows.append([str(cell).strip() if cell is not None else "" for cell in row])

    if not rows:
        return ""

    header = rows[0]
    has_year_cols = any(_is_year_header(h) for h in header[1:])  # skip first col (row labels)

    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    for row in rows[1:]:
        # Pad row to match header width
        while len(row) < len(header):
            row.append("")

        if has_year_cols:
            # Annotate each cell with its column header for clarity
            annotated = []
            for col_idx, cell in enumerate(row):
                if col_idx == 0:
                    annotated.append(cell)  # row label — no annotation needed
                elif cell:
                    col_head = header[col_idx] if col_idx < len(header) else ""
                    annotated.append(f"{col_head}: {cell}" if col_head else cell)
                else:
                    annotated.append("")
            lines.append("| " + " | ".join(annotated) + " |")
        else:
            lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main ingestion function
# ---------------------------------------------------------------------------

_DIGIT_RE = re.compile(r"\d")
_FINANCIAL_TABLE_RE = re.compile(
    r"(income statement|balance sheet|cash flow|statement of profit|"
    r"financial statement|financial summary|statement of financial position|"
    r"segment result|remuneration report|five-year summary)",
    re.IGNORECASE,
)


def _is_financial_page(text: str, digit_threshold: int = 150) -> bool:
    """
    Targeted check to determine if a page contains primary financial statement tables.
    Requires high digit density (>=150) AND financial statement keywords in the page header.
    This runs table parsing only on true financial statement tables, completing ingestion
    in seconds instead of minutes.
    """
    if not text:
        return False
    if len(_DIGIT_RE.findall(text)) < digit_threshold:
        return False
    return bool(_FINANCIAL_TABLE_RE.search(text[:600]))


def ingest_pdf(
    pdf_path: str,
    progress_callback: Optional[callable] = None,
) -> list[PageData]:
    """
    Read the PDF and return a list of PageData objects, one per page.

    Strategy:
    - PyMuPDF (fitz) for fast, low-memory plain-text extraction and page iteration.
    - PyMuPDF native find_tables() targeted on financial statement pages.
    - Keep only {pdf_page, printed_page, text, tables_markdown} per page.
    - Never keep page images or raw PDF bytes after extraction.
    - Closes documents in finally blocks.
    """
    pages: list[PageData] = []

    fitz_doc = fitz.open(pdf_path)
    total_pages = len(fitz_doc)

    try:
        for idx in range(total_pages):
            fitz_page = fitz_doc[idx]

            # --- Plain text via PyMuPDF ---
            plain_text = fitz_page.get_text("text").strip()

            # --- Detect printed page number ---
            page_number = _detect_printed_page_number(plain_text, idx)

            # --- Tables: PyMuPDF native find_tables() on financial pages ---
            tables_md: list[str] = []
            if _is_financial_page(plain_text):
                try:
                    tabs = fitz_page.find_tables()
                    for tab in tabs:
                        raw_table = tab.extract()
                        if raw_table:
                            md = _table_to_markdown(raw_table)
                            if md:
                                tables_md.append(md)
                except Exception:
                    pass  # If table extraction fails for a page, continue

            digits_count = len(_DIGIT_RE.findall(plain_text))
            has_table = (len(tables_md) > 0) or (digits_count >= 80)

            pages.append(PageData(
                pdf_index=idx,
                page_number=page_number,
                text=plain_text,
                tables_markdown=tables_md,
                has_table=has_table,
            ))

            if progress_callback:
                progress_callback(idx + 1, total_pages)

    finally:
        fitz_doc.close()

    return pages


def get_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF without full ingestion."""
    doc = fitz.open(pdf_path)
    n = len(doc)
    doc.close()
    return n

