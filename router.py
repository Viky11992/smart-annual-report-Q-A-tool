"""
router.py
Classifies each question into one of four categories:
  - quantitative  : financial numbers, ratios, figures
  - overview      : company info, CEO, employees, stores, history
  - risk          : risks, cyber, regulatory, climate, etc.
  - comparison    : year-on-year change, FY vs FY, increase/decrease

The category drives:
  - which prompt template to use (prompts.py)
  - how many chunks to retrieve (risk → more; overview → fewer)
  - whether to boost table pages in search
"""

from __future__ import annotations

import re
from typing import Literal

QuestionType = Literal["quantitative", "overview", "risk", "comparison"]

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

_COMPARISON_KEYWORDS = [
    r"\bchange\b", r"\bchanged\b", r"\bvs\b", r"\bversus\b",
    r"\bcompare\b", r"\bcomparison\b", r"\bfy\d{4}\b.*\bfy\d{4}\b",
    r"\bfrom\s+fy", r"\bincrease\b", r"\bdecreased?\b", r"\bgrowth\b",
    r"\byear.on.year\b", r"\byoy\b", r"\bprevious year\b", r"\blast year\b",
    r"\bfy20\d\d\b.*\bfy20\d\d\b",
]

_RISK_KEYWORDS = [
    r"\brisk\b", r"\brisks\b", r"\bcyber\b", r"\bregulatory\b",
    r"\bclimate\b", r"\boperational risk\b", r"\bcredit risk\b",
    r"\bliquidity risk\b", r"\bmarket risk\b", r"\bgeopoliti", r"\bsupply.chain\b",
    r"\bcompliance\b", r"\bhazard\b", r"\bthreat\b",
]

_QUANTITATIVE_KEYWORDS = [
    r"\brevenue\b", r"\bprofit\b", r"\bearnings\b", r"\bebitda\b", r"\bebit\b",
    r"\beps\b", r"\bdividend\b", r"\bcash flow\b", r"\bcapex\b",
    r"\btotal assets\b", r"\btotal liabilities\b", r"\bnet debt\b",
    r"\bshareholders.equity\b", r"\bgearing\b", r"\bequity\b",
    r"\bnpat\b", r"\bbalance sheet\b", r"\bfinancial\b",
    r"\bmillion\b", r"\bbillion\b", r"\$", r"\bhow much\b",
    r"\bwhat was the\b.*\b(revenue|profit|income|cash|asset|debt|ebit)\b",
    r"\boperating cash\b", r"\bfree cash\b", r"\bcapital expenditure\b",
    r"\bbasic eps\b", r"\bdiluted eps\b",
]

_OVERVIEW_KEYWORDS = [
    r"\bceo\b", r"\bcfo\b", r"\bchief executive\b", r"\bchief financial\b",
    r"\bheadquarter\b", r"\bfounded\b", r"\bestablished\b", r"\bhistory\b",
    r"\bemployee\b", r"\bteam member\b", r"\bstaff\b", r"\bworkforce\b",
    r"\bsubsidiar\b", r"\bdivision\b", r"\bbusiness\b", r"\bindustr\b",
    r"\bsector\b", r"\bmarket\b", r"\bstore\b", r"\boutlet\b",
    r"\bwho is\b", r"\bwhere is\b", r"\bwhat does\b", r"\bhow many\b",
    r"\bwhen was\b", r"\bwhat are the main\b",
    r"\bmanaging director\b", r"\bhead office\b", r"\bregistered office\b",
]


def _matches(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def classify_question(question: str) -> QuestionType:
    """
    Classify a question string into one of four categories.
    Priority: comparison > risk > quantitative > overview
    """
    if _matches(question, _COMPARISON_KEYWORDS):
        return "comparison"
    if _matches(question, _RISK_KEYWORDS):
        return "risk"
    if _matches(question, _QUANTITATIVE_KEYWORDS):
        return "quantitative"
    return "overview"


def get_retrieval_config(question_type: QuestionType) -> dict:
    """
    Return retrieval parameters for a given question type.
    - risk: top_k=15 (brief explicitly says risk questions need more chunks)
    - overview: top_k=10 (CEO, HQ, store counts span multiple pages)
    - quantitative: top_k=8, boost tables for financial figures
    - comparison: top_k=8, boost tables for year-on-year lookups
    """
    configs = {
        "quantitative": {"top_k": 6,  "boost_tables": True},
        "overview":     {"top_k": 6,  "boost_tables": False},
        "risk":         {"top_k": 8,  "boost_tables": False},
        "comparison":   {"top_k": 6,  "boost_tables": True},
    }
    return configs[question_type]
