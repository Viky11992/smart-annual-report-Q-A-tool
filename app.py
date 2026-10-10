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

import hashlib
import tempfile

# ──────────────────────────────────────────────────────────────────────────────
# Cached PDF ingestion (keyed by file hash — zero duplicate in-memory data copies)
# ──────────────────────────────────────────────────────────────────────────────
MAX_PDF_BYTES = 35 * 1024 * 1024  # 35 MB hard limit for Streamlit Cloud stability


@st.cache_resource(show_spinner=False)
def _cached_ingest(file_hash: str, tmp_pdf_path: str):
    """
    Ingest and index a PDF, cached by sha256 hash.
    Using @st.cache_resource stores the objects by reference rather than
    pickling/duplicating them into memory.
    """
    pages = ingest_pdf(tmp_pdf_path)
    idx = AnnualReportIndex(pages)
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
if "pdf_hash" not in st.session_state:
    st.session_state.pdf_hash = None
if "session_results" not in st.session_state:
    st.session_state.session_results = []
if "question_input" not in st.session_state:
    st.session_state.question_input = ""

# ──────────────────────────────────────────────────────────────────────────────
# Sidebar — LLM configuration
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuration")

    # Read API Key from st.secrets first, then fall back to environment variable
    secret_key = ""
    try:
        secret_key = st.secrets.get("GROQ_API_KEY", "")
    except Exception:
        pass
    if not secret_key:
        secret_key = os.environ.get("GROQ_API_KEY", "")

    api_key = st.text_input(
        "Groq API Key",
        value=secret_key,
        type="password",
        help="Reads from Streamlit secrets (.streamlit/secrets.toml) or enter here.",
    )
    if api_key:
        os.environ["GROQ_API_KEY"] = api_key
    elif not secret_key:
        st.warning("⚠️ GROQ_API_KEY is missing. Please add it to .streamlit/secrets.toml or input above.")

    model = st.text_input(
        "Model name (optional)",
        value="openai/gpt-oss-20b",
        help="Default: openai/gpt-oss-20b via Groq.",
    )
    if model:
        os.environ["LLM_MODEL"] = model

    st.markdown("---")
    st.caption("⚡ Get a free Groq API key at [console.groq.com](https://console.groq.com/keys)")

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
    # ── File size guard without holding duplicate copies in RAM ────────────
    file_size = uploaded_file.size
    if file_size > MAX_PDF_BYTES:
        st.error(
            f"⚠️ File too large ({file_size // (1024*1024)} MB). "
            f"Please use a PDF under {MAX_PDF_BYTES // (1024*1024)} MB to ensure Streamlit Cloud memory limits are not exceeded."
        )
        st.stop()

    # Read uploaded file content once to compute hash and write to temp file
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # ── Only re-ingest if the file hash actually changed ──────────────────
    if file_hash != st.session_state.pdf_hash:
        progress_bar = st.progress(0, text="Starting document ingestion…")
        status_placeholder = st.empty()

        # Save to temp file on disk so PyMuPDF can read directly without holding bytes in memory
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        # Free the uploaded bytes immediately
        del file_bytes

        try:
            with st.spinner(f"Reading **{uploaded_file.name}** — extracting text and tables…"):
                def update_progress(current_page: int, total_pages: int):
                    pct = int((current_page / total_pages) * 100)
                    progress_bar.progress(pct, text=f"Processing page {current_page} of {total_pages}…")

                pages = ingest_pdf(tmp_path, progress_callback=update_progress)
                idx = AnnualReportIndex(pages)

            st.session_state.pages = pages
            st.session_state.index = idx
            st.session_state.pdf_name = uploaded_file.name
            st.session_state.pdf_hash = file_hash
            st.session_state.session_results = []  # reset on new document
            progress_bar.progress(100, text="Indexing complete!")
            time.sleep(0.3)
            progress_bar.empty()
            st.success(f"✅ **{uploaded_file.name}** loaded — {len(pages)} pages indexed.")
        except Exception as e:
            st.error(f"❌ Failed to ingest PDF: {e}")
            st.stop()
        finally:
            import gc
            gc.collect()
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

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
    active_key = os.environ.get("GROQ_API_KEY", "")
    if not active_key:
        st.error("⚠️ Please configure your GROQ_API_KEY in the sidebar or via .streamlit/secrets.toml before asking questions.")
        st.stop()

    with st.spinner("🔎 Searching the report and extracting answer…"):
        try:
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
        except Exception as e:
            st.error(f"❌ Error extracting answer: {e}")
            st.stop()


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
