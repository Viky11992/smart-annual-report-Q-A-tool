"""
export.py
Exports Q&A session results to an Excel workbook with two sheets:
  - Sheet 1 "Results": one row per question with all answer fields
  - Sheet 2 "Sources": one row per question with the verbatim quote and page
Numbers are stored as actual numeric cells (not text) with thousands separators.
"""

from __future__ import annotations

import io
from typing import Any

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")     # dark blue
FOUND_FILL = PatternFill("solid", fgColor="C6EFCE")      # light green
AMBIG_FILL = PatternFill("solid", fgColor="FFEB9C")      # light amber
NOT_FOUND_FILL = PatternFill("solid", fgColor="FFC7CE")  # light red
ALT_ROW_FILL = PatternFill("solid", fgColor="EBF3FA")    # very light blue
WHITE_FILL = PatternFill("solid", fgColor="FFFFFF")

HEADER_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
NORMAL_FONT = Font(name="Calibri", size=10)

THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

RESULTS_COLUMNS = [
    ("ID", 6),
    ("Question", 55),
    ("Answer", 40),
    ("Numeric Value", 18),
    ("Unit", 16),
    ("Period", 14),
    ("Scope", 18),
    ("Status", 12),
    ("Confidence", 12),
    ("Page", 8),
    ("Supporting Text", 60),
    ("Explanation", 55),
]

SOURCES_COLUMNS = [
    ("ID", 6),
    ("Question", 55),
    ("Page", 8),
    ("Supporting Text", 80),
    ("Status", 12),
    ("Verification Flags", 40),
]

COMPARISON_COLUMNS = [
    ("ID", 6),
    ("Question", 55),
    ("Year A", 12),
    ("Value A", 18),
    ("Source Page A", 14),
    ("Year B", 12),
    ("Value B", 18),
    ("Source Page B", 14),
    ("Dollar Change", 18),
    ("% Change", 12),
    ("Unit", 16),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_header(ws, columns: list[tuple[str, int]]) -> None:
    for col_idx, (col_name, col_width) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = col_width
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"


def _status_fill(status: str) -> PatternFill:
    if status == "Found":
        return FOUND_FILL
    if status == "Ambiguous":
        return AMBIG_FILL
    return NOT_FOUND_FILL


def _set_row_style(ws, row_idx: int, ncols: int, fill: PatternFill) -> None:
    for col in range(1, ncols + 1):
        cell = ws.cell(row=row_idx, column=col)
        cell.font = NORMAL_FONT
        cell.fill = fill
        cell.border = THIN_BORDER
        cell.alignment = Alignment(vertical="top", wrap_text=True)


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def build_excel(session_results: list[dict[str, Any]]) -> bytes:
    """
    Given a list of answer dicts (one per question asked in the session),
    build and return an Excel workbook as bytes.
    """
    wb = openpyxl.Workbook()

    # -----------------------------------------------------------------------
    # Sheet 1: Results
    # -----------------------------------------------------------------------
    ws_results = wb.active
    ws_results.title = "Results"
    _write_header(ws_results, RESULTS_COLUMNS)

    for i, item in enumerate(session_results, start=1):
        row = i + 1
        status = item.get("status", "Not Found")

        # Numeric value — store as real number
        raw_num = item.get("numeric_value")
        try:
            num_val = float(raw_num) if raw_num is not None else None
        except (TypeError, ValueError):
            num_val = None

        ws_results.cell(row=row, column=1, value=i)
        ws_results.cell(row=row, column=2, value=item.get("question", ""))
        ws_results.cell(row=row, column=3, value=item.get("answer", ""))
        # Column 4: numeric value as a real number (not text)
        if num_val is not None:
            cell = ws_results.cell(row=row, column=4, value=num_val)
            cell.number_format = "#,##0.00"
        else:
            ws_results.cell(row=row, column=4, value="")
        ws_results.cell(row=row, column=5, value=item.get("unit", ""))
        ws_results.cell(row=row, column=6, value=item.get("period", ""))
        ws_results.cell(row=row, column=7, value=item.get("scope", ""))
        ws_results.cell(row=row, column=8, value=status)
        ws_results.cell(row=row, column=9, value=item.get("confidence", ""))
        ws_results.cell(row=row, column=10, value=item.get("page", ""))
        ws_results.cell(row=row, column=11, value=item.get("supporting_text", ""))
        ws_results.cell(row=row, column=12, value=item.get("explanation", ""))

        row_fill = _status_fill(status)
        _set_row_style(ws_results, row, len(RESULTS_COLUMNS), row_fill)
        ws_results.row_dimensions[row].height = 60

    # -----------------------------------------------------------------------
    # Sheet 2: Sources
    # -----------------------------------------------------------------------
    ws_sources = wb.create_sheet("Sources")
    _write_header(ws_sources, SOURCES_COLUMNS)

    for i, item in enumerate(session_results, start=1):
        row = i + 1
        status = item.get("status", "Not Found")
        verification = item.get("verification", {})
        flags = "; ".join(verification.get("flags", [])) if verification else ""

        ws_sources.cell(row=row, column=1, value=i)
        page_val = item.get("page", "")
        if item.get("page_a") and item.get("page_b") and item.get("page_a") != item.get("page_b"):
            page_val = f"{item.get('page_a')}, {item.get('page_b')}"
        ws_sources.cell(row=row, column=3, value=page_val)
        ws_sources.cell(row=row, column=4, value=item.get("supporting_text", ""))
        ws_sources.cell(row=row, column=5, value=status)
        ws_sources.cell(row=row, column=6, value=flags)

        row_fill = _status_fill(status)
        _set_row_style(ws_sources, row, len(SOURCES_COLUMNS), row_fill)
        ws_sources.row_dimensions[row].height = 80

    # -----------------------------------------------------------------------
    # Sheet 3: Comparisons (only if any comparison answers exist)
    # -----------------------------------------------------------------------
    comparison_items = [r for r in session_results if r.get("comparison")]
    if comparison_items:
        ws_comp = wb.create_sheet("Comparisons")
        _write_header(ws_comp, COMPARISON_COLUMNS)

        for i, item in enumerate(comparison_items, start=1):
            row = i + 1
            comp = item["comparison"]
            years = [k for k in comp if k not in ("dollar_change", "pct_change", "unit")]
            year_a = years[0] if len(years) > 0 else ""
            year_b = years[1] if len(years) > 1 else ""

            a_data = comp.get(year_a, {})
            b_data = comp.get(year_b, {})
            dollar_change = comp.get("dollar_change")
            pct_change = comp.get("pct_change")

            ws_comp.cell(row=row, column=1, value=i)
            ws_comp.cell(row=row, column=2, value=item.get("question", ""))
            ws_comp.cell(row=row, column=3, value=year_a)
            if a_data.get("value") is not None:
                cell = ws_comp.cell(row=row, column=4, value=float(a_data["value"]))
                cell.number_format = "#,##0.00"
            ws_comp.cell(row=row, column=5, value=a_data.get("page", ""))
            ws_comp.cell(row=row, column=6, value=year_b)
            if b_data.get("value") is not None:
                cell = ws_comp.cell(row=row, column=7, value=float(b_data["value"]))
                cell.number_format = "#,##0.00"
            ws_comp.cell(row=row, column=8, value=b_data.get("page", ""))
            if dollar_change is not None:
                cell = ws_comp.cell(row=row, column=9, value=float(dollar_change))
                cell.number_format = "#,##0.00"
            if pct_change is not None:
                cell = ws_comp.cell(row=row, column=10, value=float(pct_change) / 100)
                cell.number_format = "0.00%"
            ws_comp.cell(row=row, column=11, value=comp.get("unit", ""))

            _set_row_style(ws_comp, row, len(COMPARISON_COLUMNS), WHITE_FILL)
            ws_comp.row_dimensions[row].height = 40

    # -----------------------------------------------------------------------
    # Serialise to bytes
    # -----------------------------------------------------------------------
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()
