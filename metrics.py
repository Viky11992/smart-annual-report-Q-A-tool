"""
metrics.py
Finance synonym dictionary used to expand query terms before BM25 search.
This ensures questions phrased one way still match pages that use different terminology.
"""

# Each entry maps a canonical term to a list of synonyms (and vice versa).
# Keys and values are all lower-case.
SYNONYM_GROUPS: list[list[str]] = [
    # CEO / Managing Director
    ["ceo", "chief executive officer", "chief executive", "managing director",
     "managing director and chief executive", "group managing director",
     "executive leadership", "group ceo"],

    # CFO / Finance Director
    ["cfo", "chief financial officer", "finance director", "group cfo",
     "chief financial", "head of finance"],

    # Headquarters / Location
    ["headquarters", "head office", "headquartered", "registered office",
     "principal office", "corporate office", "based in", "location"],

    # Number of employees / team members
    ["employees", "team members", "workforce", "headcount",
     "number of employees", "number of team members", "staff",
     "people employed", "employed"],

    # Material risks / risk management
    ["material risk", "material risks", "principal risks", "key risks",
     "risk management", "risk factors", "significant risks",
     "identified risks", "risk overview"],

    # Cyber risk
    ["cyber", "cybersecurity", "cyber security", "cyber risk",
     "information security", "data breach", "cyber attack",
     "cyber threat", "it security", "digital security"],

    # Stores / outlets
    ["stores", "store network", "number of stores", "outlets",
     "retail locations", "locations", "branches", "store count"],

    # Revenue
    ["revenue", "sales", "total revenue", "net revenue", "total sales",
     "revenue from operations", "total income", "operating revenue"],

    # Net profit after tax
    ["net profit after tax", "npat", "profit after tax", "net profit",
     "profit attributable to members", "profit attributable to owners",
     "profit for the period", "profit for the year", "net income",
     "net earnings"],

    # EBITDA
    ["ebitda", "earnings before interest tax depreciation amortisation",
     "earnings before interest tax depreciation and amortisation"],

    # EBIT
    ["ebit", "earnings before interest and tax",
     "earnings before interest tax", "operating profit"],

    # EPS
    ["eps", "earnings per share", "basic eps", "diluted eps",
     "basic earnings per share", "diluted earnings per share"],

    # Dividend
    ["dividend", "dividends per share", "dps", "distribution",
     "final dividend", "interim dividend"],

    # Operating cash flow
    ["operating cash flow", "net cash from operating activities",
     "cash flow from operations", "cash generated from operations",
     "operating cash flows"],

    # Capital expenditure
    ["capital expenditure", "capex", "purchases of property plant and equipment",
     "additions to property plant and equipment", "investment in property plant equipment",
     "capital spending"],

    # Free cash flow
    ["free cash flow", "fcf", "operating cash flow less capex"],

    # Total assets
    ["total assets", "assets", "total group assets"],

    # Total liabilities
    ["total liabilities", "liabilities"],

    # Net debt
    ["net debt", "net borrowings", "total debt less cash"],

    # Total debt / borrowings
    ["total debt", "borrowings", "total borrowings", "interest bearing liabilities",
     "interest-bearing liabilities", "debt"],

    # Cash
    ["cash", "cash and cash equivalents", "cash at bank",
     "cash and short term investments"],

    # Equity / shareholders equity
    ["shareholders equity", "equity", "total equity",
     "total shareholders equity", "net assets",
     "equity attributable to members", "equity attributable to owners"],

    # Return on equity
    ["return on equity", "roe"],

    # Return on assets
    ["return on assets", "roa"],

    # Gearing
    ["gearing", "gearing ratio", "leverage", "debt to equity"],

    # Employees / team members
    ["employees", "team members", "workforce", "headcount",
     "number of employees", "number of team members", "staff"],
]


def build_synonym_map() -> dict[str, list[str]]:
    """
    Returns a flat dict: every term → list of all synonyms in its group
    (including itself, so lookups are uniform).
    """
    mapping: dict[str, list[str]] = {}
    for group in SYNONYM_GROUPS:
        for term in group:
            mapping[term.lower()] = [t.lower() for t in group]
    return mapping


SYNONYM_MAP: dict[str, list[str]] = build_synonym_map()


def expand_query(query: str) -> str:
    """
    Given a question string, return an expanded string that appends
    all synonym terms found so BM25 sees more matching tokens.
    """
    query_lower = query.lower()
    extra_terms: list[str] = []
    for term, synonyms in SYNONYM_MAP.items():
        if term in query_lower:
            extra_terms.extend(synonyms)
    if extra_terms:
        return query + " " + " ".join(extra_terms)
    return query
