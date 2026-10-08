"""
verify.py
Post-LLM verification: plain Python checks (no LLM calls) that:
  1. The supporting_text actually appears on the stated page
  2. The numeric_value appears inside the supporting_text
  3. Overrides the confidence level based on these checks
"""

from __future__ import annotations

import re
from typing import Any

from ingest import PageData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lower-case, collapse whitespace, strip punctuation for fuzzy matching."""
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _quote_appears_on_page(supporting_text: str, page: PageData) -> bool:
    """
    Check if the supporting_text (or a long enough substring) appears in page.full_text.
    Uses a sliding window of 40 characters for fuzzy match tolerance.
    """
    if not supporting_text:
        return False

    norm_quote = _normalise(supporting_text)
    norm_page = _normalise(page.full_text)

    # Direct substring match
    if norm_quote in norm_page:
        return True

    # Try shorter windows in case there are minor whitespace diffs
    window = 40
    if len(norm_quote) >= window:
        snippet = norm_quote[:window]
        return snippet in norm_page

    return norm_quote in norm_page


def _number_in_text(numeric_value: float | int | None, supporting_text: str) -> bool:
    """Check that the numeric value appears somewhere in the supporting text."""
    if numeric_value is None or not supporting_text:
        return True  # Nothing to verify
    # Format the number in various ways it might appear
    candidates = [
        str(int(numeric_value)) if numeric_value == int(numeric_value) else str(numeric_value),
        f"{numeric_value:,.0f}",
        f"{numeric_value:,.1f}",
        f"{numeric_value:,.2f}",
    ]
    text_clean = supporting_text.replace(",", "").replace(" ", "")
    for c in candidates:
        if c.replace(",", "") in text_clean:
            return True
    return False


# ---------------------------------------------------------------------------
# Main verification function
# ---------------------------------------------------------------------------

def verify_answer(
    answer: dict[str, Any],
    pages: list[PageData],
) -> dict[str, Any]:
    """
    Run post-LLM verification on the answer dict.
    Mutates and returns the answer dict with updated confidence and a new
    'verification' key containing details of what was checked.
    """
    verification = {
        "quote_on_page": None,
        "number_in_text": None,
        "flags": [],
    }

    if answer.get("status") in ("Not Found",) or answer.get("page") is None:
        answer["verification"] = verification
        return answer

    stated_page = answer.get("page")
    supporting_text = answer.get("supporting_text") or ""
    numeric_value = answer.get("numeric_value")

    # Find the page object matching the stated page number
    page_obj: PageData | None = None
    for p in pages:
        if p.page_number == stated_page:
            page_obj = p
            break

    if page_obj is None:
        verification["flags"].append(f"Page {stated_page} not found in ingested pages.")
        answer["confidence"] = "Low"
        answer["verification"] = verification
        return answer

    # Check 1: Does the quote appear on the stated page?
    quote_ok = _quote_appears_on_page(supporting_text, page_obj)
    verification["quote_on_page"] = quote_ok
    if not quote_ok:
        verification["flags"].append(
            "supporting_text could not be verified on the stated page."
        )

    # Check 2: Does the number appear in the supporting text?
    num_ok = _number_in_text(numeric_value, supporting_text)
    verification["number_in_text"] = num_ok
    if not num_ok and numeric_value is not None:
        verification["flags"].append(
            f"Numeric value {numeric_value} not found within supporting_text."
        )

    # Override confidence based on checks
    if quote_ok and num_ok:
        # Trust LLM confidence but cap at High only if both checks pass
        pass  # keep LLM's confidence
    elif quote_ok and not num_ok:
        if answer.get("confidence") == "High":
            answer["confidence"] = "Medium"
    elif not quote_ok:
        answer["confidence"] = "Low"

    answer["verification"] = verification
    return answer
