# Annual Report Q&A Tool

An AI-powered web app that answers questions about company annual reports with **exact page citations and verbatim quotes**.

> Built for FYP · Tested on Wesfarmers Annual Report FY2025

---

## 🚀 Quick Start (Local)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your API key
Create a `.env` file (never commit this):
```
GROQ_API_KEY=gsk_...
# or:
ANTHROPIC_API_KEY=sk-ant-...
# or:
OPENAI_API_KEY=sk-...
# or:
GEMINI_API_KEY=...
```
Or set it in the Streamlit sidebar at runtime (free Groq API keys available at [console.groq.com](https://console.groq.com/keys)).

### 3. Run the app
```bash
streamlit run app.py
```

### 4. Try it
1. Upload a PDF annual report (e.g. Wesfarmers FY2025)
2. Ask: *"What was the revenue in FY2025?"*
3. Ask: *"How did net profit change from FY2024 to FY2025?"*

---

## 📊 Features

| Feature | Description |
|---|---|
| **Cited answers** | Every answer links to an exact page number and verbatim quote |
| **Status badge** | 🟢 Found · 🟡 Ambiguous · 🔴 Not Found |
| **Confidence** | High / Medium / Low — code-verified, not just LLM self-rating |
| **YoY comparison** | Extracts both years separately; calculates change in Python |
| **Group vs Division** | Distinguishes consolidated Group figures from subsidiary figures |
| **Excel export** | Numbers stored as real numerics; three sheets: Results, Sources, Comparisons |
| **Finance synonyms** | NPAT = net profit after tax = profit attributable to members, etc. |
| **No hallucinations** | LLM instructed to return "Not Found" if answer not in retrieved text |

---

## 🏗️ Project Structure

```
fyp-aus/
├── app.py          # Streamlit UI
├── ingest.py       # PDF page + table extraction
├── index.py        # BM25 search index
├── metrics.py      # Finance synonym dictionary
├── router.py       # Question classifier
├── prompts.py      # LLM prompt templates
├── extract.py      # LLM call + JSON parser
├── verify.py       # Post-LLM quote verification
├── compare.py      # Year-on-year comparison logic
├── export.py       # Excel workbook builder
├── eval/
│   ├── run_eval.py # Evaluation script
│   ├── questions.csv
│   └── results/    # Timestamped evaluation CSVs
└── requirements.txt
```

---

## 🧪 Running the Evaluation

```bash
python eval/run_eval.py --pdf path/to/wesfarmers-fy2025.pdf
```

Results are saved to `eval/results/eval_results_YYYYMMDD_HHMMSS.csv`.

---

## ☁️ Deployment (Streamlit Community Cloud)

1. Push to GitHub (private repo).
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Select this repo, branch `main`, file `app.py`.
4. In **Advanced settings → Secrets**, add:
   ```toml
   GROQ_API_KEY = "gsk_..."
   LLM_PROVIDER = "groq"
   ```
5. Click **Deploy**.

---

## ⚠️ Limitations

- **Text-based PDFs only** — scanned/image PDFs are not supported.
- No model training; uses LLM APIs at temperature=0.
- Cannot perform complex financial calculations.
- Figures not present in the PDF text return "Not Found".

---

## 📋 LLM Provider Support

| Provider | Env var | Default model | Free tier |
|---|---|---|---|
| **Groq (Llama 3.3)** | `GROQ_API_KEY` | `llama-3.3-70b-versatile` | ✅ Yes (free API key) |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-20241022` | Paid |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o` | Paid |
| Google Gemini | `GEMINI_API_KEY` | `gemini-1.5-pro` | Free tier / Paid |

Set `LLM_PROVIDER` to `groq`, `anthropic`, `openai`, or `gemini`.
