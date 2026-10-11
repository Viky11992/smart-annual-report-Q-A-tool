"""
prompts.py
LLM prompt templates for each question type.
All prompts instruct the LLM to:
  - Use only the provided excerpts
  - Return strict JSON matching the output schema
  - Copy supporting text verbatim
  - Check year column headings before returning numbers
  - Distinguish Group-level vs division/subsidiary figures
  - Return status "Not Found" if the answer is not in the excerpts
  - Return status "Ambiguous" if multiple conflicting values exist
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared output schema description (injected into every prompt)
# ---------------------------------------------------------------------------

OUTPUT_SCHEMA = """
Return ONLY valid JSON with these exact keys and nothing else:
{
  "answer": "<concise answer, e.g. AUD 45,503 million>",
  "numeric_value": <number or null>,
  "unit": "<e.g. AUD million, %, cents, or null>",
  "period": "<e.g. FY2025, year ended 30 June 2025, or null>",
  "scope": "<Group | Division name | Subsidiary name | null>",
  "status": "<Found | Not Found | Ambiguous>",
  "confidence": "<High | Medium | Low>",
  "page": <integer page number or null>,
  "supporting_text": "<exact verbatim quote from the report, or null>",
  "explanation": "<brief explanation of what the figure means and any caveats>",
  "other_values": [
    {
      "answer": "...",
      "page": ...,
      "supporting_text": "...",
      "explanation": "..."
    }
  ]
}

Rules you MUST follow:
1. Use ONLY the provided excerpts. Do not use outside knowledge.
2. Copy supporting_text EXACTLY as it appears in the excerpts. Do not paraphrase or summarise.
3. Before returning a number from a table, confirm the column heading matches the requested year.
4. State the figure scope as "Group" or the specific division/subsidiary name.
5. If the answer is NOT in the excerpts, set status to "Not Found", answer to "Not found in the report", and all other fields to null.
6. If multiple different values exist for the same metric (e.g. in different tables, or Group-level vs division-level, or FY2025 vs FY2024 columns), set status to "Ambiguous" and list each value in other_values with its own page and supporting_text.
7. Set confidence: "High" if you found an exact match; "Medium" if you inferred it; "Low" if you are uncertain.
8. Do NOT guess, calculate, or derive figures unless explicitly asked in a comparison question.
9. Return only the JSON object. No markdown code fences, no extra text.
"""

# ---------------------------------------------------------------------------
# System message (same for all question types)
# ---------------------------------------------------------------------------

SYSTEM_MESSAGE = (
    "You are a precise financial document analyst. "
    "You extract factual information from annual report excerpts. "
    "You never guess or use outside knowledge. "
    "You always cite exact page numbers and verbatim quotes."
)

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _format_chunks(chunks: list, max_total_chars: int = 6500) -> str:
    """
    Format retrieved chunks into excerpts string.
    Caps total characters to ~6,500 chars (~1,500 tokens) so that the entire prompt
    stays around ~1,800-2,000 tokens, allowing 4+ questions per minute without
    hitting Groq's 8,000 TPM limit.
    """
    parts = []
    total_chars = 0
    for chunk in chunks:
        entry = f"--- Page {chunk.page_number} ---\n{chunk.text}"
        if total_chars + len(entry) > max_total_chars and parts:
            # Add truncated entry if space remains
            remaining = max_total_chars - total_chars
            if remaining > 300:
                parts.append(f"--- Page {chunk.page_number} ---\n{chunk.text[:remaining]}...")
            break
        parts.append(entry)
        total_chars += len(entry)
    return "\n\n".join(parts)


def build_quantitative_prompt(question: str, chunks: list) -> str:
    excerpts = _format_chunks(chunks)
    return f"""You are analysing excerpts from a company annual report to answer a financial question.

QUESTION:
{question}

ANNUAL REPORT EXCERPTS:
{excerpts}

INSTRUCTIONS:
- Find the specific numerical value requested.
- Check the table column headings to confirm you are reading the correct year.
- State the unit (e.g. AUD million, %, cents per share) and fiscal period exactly as written.
- If the figure appears at both Group level and division level, prefer Group level unless the question asks for a specific division.
- If the number appears in a table, include the table row/column context in supporting_text.

{OUTPUT_SCHEMA}"""


def build_overview_prompt(question: str, chunks: list) -> str:
    excerpts = _format_chunks(chunks)
    return f"""You are analysing excerpts from a company annual report to answer a company overview question.

QUESTION:
{question}

ANNUAL REPORT EXCERPTS:
{excerpts}

INSTRUCTIONS:
- Extract only factual information stated in the excerpts.
- For LEADERSHIP questions (CEO, CFO, Managing Director, Chairman):
    * Look for names in the Board of Directors section, letters to shareholders, or executive profiles.
    * Include the person's full name and exact title as written in the report.
    * The CEO may be titled "Managing Director and Chief Executive Officer" or similar.
- For STORE COUNT questions (Bunnings stores, Kmart stores, Officeworks stores):
    * Look for tables showing store or outlet counts by banner/brand.
    * State the number and any qualifying region (e.g. Australia and New Zealand).
- For EMPLOYEE / TEAM MEMBER questions:
    * Look for "team members", "employees", "workforce", or "headcount" figures.
    * State the number and whether it is full-time equivalent or headcount.
- For HEADQUARTERS questions:
    * Look for "registered office", "principal office", or "head office" in the report.
    * State the city and state/country exactly as written.
- For BUSINESS SEGMENTS / SUBSIDIARIES:
    * List all subsidiaries or divisions mentioned in the report.
- For lists (e.g. subsidiaries, business segments), include all items mentioned.

{OUTPUT_SCHEMA}"""


def build_risk_prompt(question: str, chunks: list) -> str:
    excerpts = _format_chunks(chunks)
    return f"""You are analysing excerpts from a company annual report to answer a question about risks.

QUESTION:
{question}

ANNUAL REPORT EXCERPTS:
{excerpts}

INSTRUCTIONS:
- Identify all relevant risk factors mentioned in the excerpts.
- For each risk, note the risk category, description, and any mitigating actions mentioned.
- If asking for a specific risk (e.g. cyber risk), focus on that risk and its management actions.
- If asking "what are the risks", summarise all material risks listed.
- The answer may be long — include all relevant detail.

{OUTPUT_SCHEMA}"""


def build_comparison_prompt(question: str, chunks: list) -> str:
    excerpts = _format_chunks(chunks)
    return f"""You are analysing excerpts from a company annual report to answer a year-on-year comparison question.

QUESTION:
{question}

ANNUAL REPORT EXCERPTS:
{excerpts}

INSTRUCTIONS:
- Extract the value for EACH year mentioned in the question separately.
- Confirm the column heading for each year before returning its value.
- Do NOT calculate the change — return the raw values and their page/quote; the change will be calculated in code.
- If only one year's value is available, return what you found and note that the other year was not found.
- Return both values in other_values if you find two distinct year figures.

{OUTPUT_SCHEMA}"""


def get_prompt(question_type: str, question: str, chunks: list) -> str:
    builders = {
        "quantitative": build_quantitative_prompt,
        "overview":     build_overview_prompt,
        "risk":         build_risk_prompt,
        "comparison":   build_comparison_prompt,
    }
    builder = builders.get(question_type, build_overview_prompt)
    return builder(question, chunks)
