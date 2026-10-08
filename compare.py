"""
compare.py
Handles year-on-year comparison questions.
Extracts the value for each year separately (each with its own page + quote),
then calculates dollar change and percentage change in Python — never in the LLM.
"""

from __future__ import annotations

import re
from typing import Any

from extract import extract_answer
from verify import verify_answer
from ingest import PageData
from index import AnnualReportIndex


# ---------------------------------------------------------------------------
# Year extraction
# ---------------------------------------------------------------------------

_FY_RE = re.compile(r"\bfy\s*(\d{4})\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _extract_years(question: str) -> list[str]:
    """Extract fiscal year labels from the question, e.g. ['FY2024', 'FY2025']."""
    years = []
    for m in _FY_RE.finditer(question):
        years.append(f"FY{m.group(1)}")
    if not years:
        for m in _YEAR_RE.finditer(question):
            years.append(m.group(1))
    return list(dict.fromkeys(years))  # deduplicate preserving order


def _make_year_question(original: str, year: str) -> str:
    """Rewrite the question to target a specific year."""
    return f"{original.strip()} — focus specifically on {year}."


# ---------------------------------------------------------------------------
# Change calculation
# ---------------------------------------------------------------------------

def _compute_change(val_a: float | None, val_b: float | None) -> dict[str, Any]:
    """
    Compute change from val_a (earlier) to val_b (later).
    Returns dollar_change and pct_change, or None if values are missing.
    """
    if val_a is None or val_b is None:
        return {"dollar_change": None, "pct_change": None}
    dollar = val_b - val_a
    pct = (dollar / abs(val_a) * 100) if val_a != 0 else None
    return {
        "dollar_change": round(dollar, 4),
        "pct_change": round(pct, 2) if pct is not None else None,
    }


# ---------------------------------------------------------------------------
# Main comparison function
# ---------------------------------------------------------------------------

def answer_comparison(
    question: str,
    index: AnnualReportIndex,
    pages: list[PageData],
) -> dict[str, Any]:
    """
    For a comparison question:
    1. Extract the two years from the question
    2. For each year, retrieve chunks and call the LLM separately
    3. Verify each answer
    4. Calculate the change in Python
    5. Return a combined result
    """
    years = _extract_years(question)

    if len(years) < 2:
        # Fall back to single extraction if we can't find two years
        from router import get_retrieval_config
        cfg = get_retrieval_config("comparison")
        chunks = index.search(question, top_k=cfg["top_k"], boost_tables=cfg["boost_tables"])
        answer = extract_answer(question, "comparison", chunks)
        answer = verify_answer(answer, pages)
        answer["comparison"] = None
        return answer

    year_a, year_b = years[0], years[1]

    results: dict[str, Any] = {}
    numeric_vals: dict[str, float | None] = {}

    for year in [year_a, year_b]:
        year_q = _make_year_question(question, year)
        # Search with the year-specific question
        chunks = index.search(year_q, top_k=8, boost_tables=True)
        ans = extract_answer(year_q, "quantitative", chunks)
        ans = verify_answer(ans, pages)
        results[year] = ans
        numeric_vals[year] = ans.get("numeric_value")

    # Calculate change: from year_a to year_b
    change = _compute_change(numeric_vals.get(year_a), numeric_vals.get(year_b))
    unit = results[year_b].get("unit") or results[year_a].get("unit")

    # Build combined answer
    combined: dict[str, Any] = {
        "answer": _format_comparison_answer(results, year_a, year_b, change, unit),
        "numeric_value": numeric_vals.get(year_b),
        "unit": unit,
        "period": f"{year_a} to {year_b}",
        "scope": results[year_b].get("scope") or results[year_a].get("scope"),
        "status": _combined_status(results, year_a, year_b),
        "confidence": _combined_confidence(results, year_a, year_b),
        "page": results[year_b].get("page"),
        "supporting_text": results[year_b].get("supporting_text"),
        "explanation": (
            f"{year_a} value: {results[year_a].get('answer')} "
            f"(page {results[year_a].get('page')}). "
            f"{year_b} value: {results[year_b].get('answer')} "
            f"(page {results[year_b].get('page')})."
        ),
        "other_values": [
            {
                "answer": results[year_a].get("answer"),
                "page": results[year_a].get("page"),
                "supporting_text": results[year_a].get("supporting_text"),
                "explanation": f"{year_a} value",
            },
            {
                "answer": results[year_b].get("answer"),
                "page": results[year_b].get("page"),
                "supporting_text": results[year_b].get("supporting_text"),
                "explanation": f"{year_b} value",
            },
        ],
        "comparison": {
            year_a: {
                "value": numeric_vals.get(year_a),
                "answer": results[year_a].get("answer"),
                "page": results[year_a].get("page"),
                "supporting_text": results[year_a].get("supporting_text"),
            },
            year_b: {
                "value": numeric_vals.get(year_b),
                "answer": results[year_b].get("answer"),
                "page": results[year_b].get("page"),
                "supporting_text": results[year_b].get("supporting_text"),
            },
            "dollar_change": change["dollar_change"],
            "pct_change": change["pct_change"],
            "unit": unit,
        },
    }
    return combined


def _format_comparison_answer(
    results: dict,
    year_a: str,
    year_b: str,
    change: dict,
    unit: str | None,
) -> str:
    a_ans = results[year_a].get("answer", "Not found")
    b_ans = results[year_b].get("answer", "Not found")
    unit_str = f" {unit}" if unit else ""
    lines = [f"{year_a}: {a_ans}", f"{year_b}: {b_ans}"]
    if change["dollar_change"] is not None:
        direction = "increased" if change["dollar_change"] >= 0 else "decreased"
        lines.append(
            f"Change: {direction} by {abs(change['dollar_change']):,.2f}{unit_str} "
            f"({change['pct_change']:+.1f}%)"
            if change["pct_change"] is not None
            else f"Change: {direction} by {abs(change['dollar_change']):,.2f}{unit_str}"
        )
    return " | ".join(lines)


def _combined_status(results: dict, year_a: str, year_b: str) -> str:
    sa = results[year_a].get("status", "Not Found")
    sb = results[year_b].get("status", "Not Found")
    if sa == "Found" and sb == "Found":
        return "Found"
    if sa == "Not Found" and sb == "Not Found":
        return "Not Found"
    return "Ambiguous"


def _combined_confidence(results: dict, year_a: str, year_b: str) -> str:
    order = {"High": 3, "Medium": 2, "Low": 1}
    ca = results[year_a].get("confidence", "Low")
    cb = results[year_b].get("confidence", "Low")
    return ca if order.get(ca, 1) <= order.get(cb, 1) else cb
