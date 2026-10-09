"""
eval/run_eval.py
Evaluation script for the Annual Report Q&A pipeline.

Usage:
    python eval/run_eval.py --pdf path/to/report.pdf [--questions eval/questions.csv]

Runs every question through the pipeline, saves a timestamped results CSV,
and prints accuracy by level and group.

Run repeatedly to compare before/after each code fix.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import io

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure the project root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from ingest import ingest_pdf
from index import AnnualReportIndex
from router import classify_question, get_retrieval_config
from extract import extract_answer
from verify import verify_answer
from compare import answer_comparison


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_correct(result: dict, row: dict) -> bool:
    """
    A result is "correct" if:
    - answerable=no and status="Not Found"
    - answerable=yes and status="Found" or "Ambiguous", with supporting evidence
    """
    answerable = row.get("answerable", "yes").strip().lower()
    status = result.get("status", "Not Found")
    if answerable == "no":
        return status == "Not Found"

    if status not in ("Found", "Ambiguous"):
        return False

    # For answerable questions, verify that an answer or quote exists
    if not (result.get("answer") or result.get("supporting_text")):
        return False

    # Check if page is reasonably close to expected page if ground truth page is specified
    correct_page = row.get("correct_page", "").strip()
    result_page = str(result.get("page") or "").strip()
    if correct_page and result_page:
        try:
            if abs(int(result_page) - int(correct_page)) <= 2:
                return True
        except ValueError:
            pass

    return True


def run_eval(pdf_path: str, questions_path: str, output_dir: str) -> None:
    print(f"\n{'='*60}")
    print(f"Annual Report Q&A Evaluation")
    print(f"PDF:       {pdf_path}")
    print(f"Questions: {questions_path}")
    print(f"{'='*60}\n")

    # ── Ingest ──────────────────────────────────────────────────────────────
    print("Ingesting PDF…")
    t0 = time.time()
    pages = ingest_pdf(pdf_path)
    idx = AnnualReportIndex(pages)
    print(f"Ingested {len(pages)} pages in {time.time()-t0:.1f}s\n")

    # ── Load questions ───────────────────────────────────────────────────────
    with open(questions_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        questions = list(reader)

    # ── Run pipeline ─────────────────────────────────────────────────────────
    results = []
    delay_secs = float(os.environ.get("EVAL_DELAY", "1.0"))  # seconds between questions

    for i, row in enumerate(questions):
        q_id = row["id"]
        question = row["question"].strip()
        level = row.get("level", "").strip()
        group = row.get("group", "").strip()
        answerable = row.get("answerable", "yes").strip().lower()

        print(f"[{q_id:>3}] {question[:70]}")

        t_start = time.time()
        try:
            q_type = classify_question(question)

            if q_type == "comparison":
                answer = answer_comparison(question, idx, pages)
            else:
                cfg = get_retrieval_config(q_type)
                chunks = idx.search(
                    question,
                    top_k=cfg["top_k"],
                    boost_tables=cfg["boost_tables"],
                )
                answer = extract_answer(question, q_type, chunks)
                answer = verify_answer(answer, pages)

        except Exception as e:
            answer = {
                "answer": f"ERROR: {e}",
                "status": "Not Found",
                "confidence": "Low",
                "page": None,
                "supporting_text": None,
            }

        elapsed = time.time() - t_start
        correct = _is_correct(answer, row)
        status_sym = "[PASS]" if correct else "[FAIL]"
        print(
            f"       {status_sym} status={answer.get('status')} "
            f"| page={answer.get('page')} "
            f"| conf={answer.get('confidence')} "
            f"| {elapsed:.1f}s"
        )

        results.append({
            "id":               q_id,
            "level":            level,
            "group":            group,
            "question":         question,
            "answerable":       answerable,
            "question_type":    classify_question(question),
            "status":           answer.get("status", ""),
            "confidence":       answer.get("confidence", ""),
            "page":             answer.get("page", ""),
            "answer":           answer.get("answer", ""),
            "supporting_text":  (answer.get("supporting_text") or "")[:300],
            "correct":          correct,
            "elapsed_s":        round(elapsed, 2),
        })

        # Rate-limit guard: pause between questions
        if i < len(questions) - 1 and delay_secs > 0:
            time.sleep(delay_secs)

    # ── Save results ─────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(output_dir) / f"eval_results_{ts}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(results[0].keys())
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResults saved → {out_path}\n")

    # ── Print accuracy summary ────────────────────────────────────────────────
    def accuracy(subset: list[dict]) -> str:
        if not subset:
            return "n/a"
        n = sum(1 for r in subset if r["correct"])
        return f"{n}/{len(subset)} ({100*n/len(subset):.0f}%)"

    print("=" * 50)
    print("ACCURACY SUMMARY")
    print("=" * 50)
    print(f"Overall:  {accuracy(results)}")
    print()

    for level in ["Easy", "Medium", "Hard"]:
        subset = [r for r in results if r["level"].lower() == level.lower()]
        print(f"  {level:<8}: {accuracy(subset)}")

    print()
    groups = sorted({r["group"] for r in results})
    for group in groups:
        subset = [r for r in results if r["group"] == group]
        print(f"  {group:<20}: {accuracy(subset)}")

    print("=" * 50)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Q&A evaluation over a PDF report.")
    parser.add_argument("--pdf", required=True, help="Path to the annual report PDF.")
    parser.add_argument(
        "--questions",
        default=str(Path(__file__).parent / "questions.csv"),
        help="Path to questions CSV (default: eval/questions.csv).",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "results"),
        help="Directory to save results CSVs (default: eval/results/).",
    )
    args = parser.parse_args()
    run_eval(args.pdf, args.questions, args.output)
