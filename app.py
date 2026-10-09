"""
app.py
Streamlit front-end for the Annual Report Q&A Tool.

Layout (top to bottom):
  1. Title and description
  2. LLM provider selector (sidebar)
  3. PDF upload with progress indicator
  4. Question box + 5 example question buttons
  5. Result card: answer, status badge, confidence, page, quote, explanation
  6. Expandable "Other values found" section
  7. Session table of all questions + Download Excel button
  8. How to use / limitations
"""

from __future__ import annotations

import os
import time
from typing import Any

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# Page config (must be first Streamlit call)
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Annual Report Q&A",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from ingest import ingest_pdf
from index import AnnualReportIndex
from router import classify_question, get_retrieval_config
from extract import extract_answer
from verify import verify_answer
from compare import answer_comparison
from export import build_excel

# ──────────────────────────────────────────────────────────────────────────────
# Cached PDF ingestion (keyed by file bytes — re-uploading same file is instant)
# ──────────────────────────────────────────────────────────────────────────────
MAX_PDF_BYTES = 50 * 1024 * 1024  # 50 MB hard limit


@st.cache_data(show_spinner=False)
def _cached_ingest(pdf_bytes: bytes, filename: str):
    """
    Ingest and index a PDF. Cached by file content so the same file
    is only processed once per Streamlit session (or until the cache is cleared).
    """
    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        pages = ingest_pdf(tmp_path)
        idx = AnnualReportIndex(pages)
    finally:
        os.unlink(tmp_path)
    return pages, idx


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────
EXAMPLE_QUESTIONS = [
    "What was the revenue in FY2025?",
    "What is the net profit after tax for FY2025?",
    "Who is the CEO and CFO?",
    "What are the material risks identified in the report?",
    "How did revenue change from FY2024 to FY2025?",
]

STATUS_COLORS = {
    "Found":     ("🟢", "#28a745"),
    "Ambiguous": ("🟡", "#ffc107"),
    "Not Found": ("🔴", "#dc3545"),
}

CONFIDENCE_COLORS = {
    "High":   "#28a745",
    "Medium": "#ffc107",
    "Low":    "#dc3545",
}

# ──────────────────────────────────────────────────────────────────────────────
# Session state initialisation
# ──────────────────────────────────────────────────────────────────────────────
if "pages" not in st.session_state:
    st.session_state.pages = None
if "index" not in st.session_state:
    st.session_state.index = None
if "pdf_name" not in st.session_state:
    st.session_state.pdf_name = None
if "session_results" not in st.session_state:
    st.session_state.session_results = []
if "question_input" not in st.session_state:
    st.session_state.question_input = ""

# ──────────────────────────────────────────────────────────────────────────────
# Sidebar — LLM configuration
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuration")

    providers = ["groq", "anthropic", "openai", "gemini"]
    current_provider = os.environ.get("LLM_PROVIDER", "groq").lower()
    default_idx = providers.index(current_provider) if current_provider in providers else 0

    provider = st.selectbox(
        "LLM Provider",
        providers,
        index=default_idx,
        help="Choose which LLM to use for extraction. Groq provides ultra-fast free API inference.",
    )
    os.environ["LLM_PROVIDER"] = provider

    model_defaults = {
        "groq":      "openai/gpt-oss-20b",
        "anthropic": "claude-3-5-sonnet-20241022",
        "openai":    "gpt-4o",
        "gemini":    "gemini-1.5-pro",
    }
    model = st.text_input(
        "Model name (optional)",
        value=model_defaults.get(provider, ""),
        help="Leave blank to use the default model for the selected provider.",
    )
    if model:
        os.environ["LLM_MODEL"] = model

    key_env = {
        "groq":      "GROQ_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai":    "OPENAI_API_KEY",
        "gemini":    "GEMINI_API_KEY",
    }
    existing_key = os.environ.get(key_env[provider], "")
    api_key = st.text_input(
        "API Key",
        value=existing_key,
        type="password",
        help="Your API key. Not stored — only used for this session.",
    )
    if api_key:
        os.environ[key_env[provider]] = api_key

    if provider == "groq":
        st.caption("⚡ Get a free Groq API key at [console.groq.com](https://console.groq.com/keys)")

    st.markdown("---")
    st.caption(
        "API keys are stored only in memory for this session. "
        "They are never written to disk or sent to GitHub."
    )

# ──────────────────────────────────────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────────────────────────────────────
st.title("📊 Annual Report Q&A Tool")
st.markdown(
    "Upload a company annual report (PDF), ask a question, "
    "and get a cited answer linked to the exact page and verbatim quote."
)
st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# PDF Upload
# ──────────────────────────────────────────────────────────────────────────────
st.subheader("1️⃣  Upload Annual Report PDF")

uploaded_file = st.file_uploader(
    "Drop your PDF here",
    type=["pdf"],
    help="Text-based PDFs only. Scanned documents are not supported.",
)

if uploaded_file is not None:
    # ── File size guard ────────────────────────────────────────────────────
    pdf_bytes = uploaded_file.getvalue()
    if len(pdf_bytes) > MAX_PDF_BYTES:
        st.error(
            f"⚠️ File too large ({len(pdf_bytes) // (1024*1024)} MB). "
            "Please use a PDF under 50 MB. Streamlit Cloud has a 60-second timeout."
        )
        st.stop()

    # ── Only re-ingest if the file content actually changed ───────────────
    if uploaded_file.name != st.session_state.pdf_name:
        with st.spinner(f"Reading **{uploaded_file.name}** — extracting text and tables…"):
            progress = st.progress(0, text="Ingesting pages…")
            pages, idx = _cached_ingest(pdf_bytes, uploaded_file.name)
            progress.progress(100, text="Done!")
            time.sleep(0.4)
            progress.empty()

        st.session_state.pages = pages
        st.session_state.index = idx
        st.session_state.pdf_name = uploaded_file.name
        st.session_state.session_results = []  # reset on new upload
        st.success(f"✅ **{uploaded_file.name}** loaded — {len(pages)} pages indexed.")

elif st.session_state.pdf_name:
    st.info(f"📄 Currently loaded: **{st.session_state.pdf_name}**")


# ──────────────────────────────────────────────────────────────────────────────
# Question Input
# ──────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("2️⃣  Ask a Question")

# Example question buttons
st.caption("Try one of these:")
btn_cols = st.columns(len(EXAMPLE_QUESTIONS))
for i, (col, eq) in enumerate(zip(btn_cols, EXAMPLE_QUESTIONS)):
    if col.button(eq, key=f"eq_{i}", use_container_width=True):
        st.session_state.question_input = eq

question = st.text_input(
    "Your question",
    value=st.session_state.question_input,
    placeholder="e.g. What was the net profit after tax in FY2025?",
    key="q_input",
)
st.session_state.question_input = question

ask_btn = st.button(
    "🔍 Get Answer",
    type="primary",
    disabled=(st.session_state.index is None or not question.strip()),
)

# ──────────────────────────────────────────────────────────────────────────────
# Answer pipeline
# ──────────────────────────────────────────────────────────────────────────────
if ask_btn and question.strip() and st.session_state.index is not None:
    # Check API key
    key_env_map = {
        "groq":      "GROQ_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai":    "OPENAI_API_KEY",
        "gemini":    "GEMINI_API_KEY",
    }
    if not os.environ.get(key_env_map[provider]):
        st.error("⚠️ Please enter your API key in the sidebar before asking a question.")
        st.stop()

    with st.spinner("🔎 Searching the report and extracting answer…"):
        q_type = classify_question(question)
        pages = st.session_state.pages
        index = st.session_state.index

        if q_type == "comparison":
            answer = answer_comparison(question, index, pages)
        else:
            cfg = get_retrieval_config(q_type)
            chunks = index.search(
                question,
                top_k=cfg["top_k"],
                boost_tables=cfg["boost_tables"],
            )
            answer = extract_answer(question, q_type, chunks)
            answer = verify_answer(answer, pages)

        answer["question"] = question
        answer["question_type"] = q_type
        st.session_state.session_results.append(answer)

    # ──────────────────────────────────────────────────────────────────────────
    # Result card
    # ──────────────────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("3️⃣  Result")

    status = answer.get("status", "Not Found")
    confidence = answer.get("confidence", "Low")
    emoji, status_color = STATUS_COLORS.get(status, ("❓", "#6c757d"))
    conf_color = CONFIDENCE_COLORS.get(confidence, "#6c757d")

    # Top row: answer + badges
    col_ans, col_badges = st.columns([3, 1])
    with col_ans:
        st.markdown(f"### {answer.get('answer', 'No answer')}")
        meta_parts = []
        if answer.get("period"):
            meta_parts.append(f"📅 {answer['period']}")
        if answer.get("scope"):
            meta_parts.append(f"🏢 {answer['scope']}")
        if answer.get("unit"):
            meta_parts.append(f"💱 {answer['unit']}")
        if meta_parts:
            st.caption("  ·  ".join(meta_parts))

    with col_badges:
        st.markdown(
            f"<div style='text-align:center'>"
            f"<span style='background:{status_color};color:white;padding:4px 12px;"
            f"border-radius:12px;font-weight:bold;font-size:14px'>{emoji} {status}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='text-align:center;margin-top:8px'>"
            f"<span style='background:{conf_color};color:white;padding:4px 12px;"
            f"border-radius:12px;font-size:12px'>Confidence: {confidence}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if answer.get("page"):
            st.markdown(
                f"<div style='text-align:center;margin-top:8px'>"
                f"<b>📄 Page {answer['page']}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Supporting quote
    if answer.get("supporting_text") and status != "Not Found":
        st.markdown("**Supporting text from report:**")
        st.markdown(
            f"> *{answer['supporting_text']}*"
        )
        # Verification flags
        verification = answer.get("verification", {})
        flags = verification.get("flags", []) if verification else []
        if flags:
            st.warning("⚠️ Verification note: " + "; ".join(flags))

    # Explanation
    if answer.get("explanation"):
        st.markdown(f"**Explanation:** {answer['explanation']}")

    # Comparison details
    if answer.get("comparison"):
        comp = answer["comparison"]
        years = [k for k in comp if k not in ("dollar_change", "pct_change", "unit")]
        if len(years) == 2:
            st.markdown("**Year-on-year comparison:**")
            c1, c2, c3 = st.columns(3)
            year_a, year_b = years[0], years[1]
            c1.metric(year_a, comp[year_a].get("answer", "—"))
            c2.metric(year_b, comp[year_b].get("answer", "—"))
            if comp.get("dollar_change") is not None:
                unit_str = comp.get("unit", "")
                delta_str = f"{comp['dollar_change']:+,.2f} {unit_str}".strip()
                pct_str = f"({comp['pct_change']:+.1f}%)" if comp.get("pct_change") else ""
                c3.metric("Change", f"{delta_str} {pct_str}".strip())

    # Other values
    other_values = answer.get("other_values") or []
    if other_values and status == "Ambiguous":
        with st.expander("📋 Other values found (click to expand)"):
            for i, ov in enumerate(other_values, 1):
                st.markdown(f"**Value {i}:** {ov.get('answer', '—')}")
                if ov.get("page"):
                    st.caption(f"Page {ov['page']}")
                if ov.get("supporting_text"):
                    st.markdown(f"> *{ov['supporting_text']}*")
                if ov.get("explanation"):
                    st.caption(ov["explanation"])
                if i < len(other_values):
                    st.markdown("---")

# ──────────────────────────────────────────────────────────────────────────────
# Session history table + Export
# ──────────────────────────────────────────────────────────────────────────────
if st.session_state.session_results:
    st.divider()
    st.subheader("4️⃣  Session History")

    rows = []
    for i, r in enumerate(st.session_state.session_results, 1):
        rows.append({
            "#":         i,
            "Question":  r.get("question", ""),
            "Answer":    r.get("answer", ""),
            "Status":    r.get("status", ""),
            "Confidence":r.get("confidence", ""),
            "Page":      r.get("page", ""),
            "Type":      r.get("question_type", ""),
        })

    import pandas as pd
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Download Excel
    excel_bytes = build_excel(st.session_state.session_results)
    st.download_button(
        label="⬇️ Download Full Results (Excel)",
        data=excel_bytes,
        file_name=f"annual_report_qa_{st.session_state.pdf_name or 'results'}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if st.button("🗑️ Clear session"):
        st.session_state.session_results = []
        st.rerun()

# ──────────────────────────────────────────────────────────────────────────────
# How to use / limitations
# ──────────────────────────────────────────────────────────────────────────────
st.divider()
with st.expander("ℹ️ How to use & Limitations"):
    st.markdown("""
**How to use:**
1. Enter your LLM API key in the sidebar (it stays in memory only).
2. Upload a text-based annual report PDF.
3. Type a question or click one of the example questions.
4. Review the answer, page citation, and verbatim quote.
5. Ask more questions — all results accumulate in the session table.
6. Click **Download Full Results** to export to Excel.

**What this tool can answer:**
- Financial figures: revenue, profit, EPS, cash flow, assets, debt, equity, dividends
- Company overview: CEO/CFO, employees, store counts, HQ, subsidiaries
- Risk information: material risks, cyber risk, regulatory risk
- Year-on-year comparisons: change from FY2024 to FY2025

**Known limitations:**
- Works only with text-based PDFs (not scanned / image-based documents).
- Cannot perform complex multi-step financial calculations.
- If a figure does not appear in the PDF text, it will return "Not Found".
- Very long reports (>400 pages) may take longer to process.
- The tool distinguishes Group-level from subsidiary/division figures where possible,
  but always verify critical figures against the original report.
""")

st.caption("Annual Report Q&A Tool · FYP · Built with Streamlit, PyMuPDF, BM25, and LLM APIs")
