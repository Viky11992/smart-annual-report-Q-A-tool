"""
extract.py
Calls the LLM with the question and retrieved chunks, parses the JSON response,
and returns a structured answer dict.

Supports: Groq, Anthropic Claude, OpenAI, Google Gemini
The provider is chosen via the LLM_PROVIDER env var (default: groq).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from prompts import SYSTEM_MESSAGE, get_prompt
from rate_limiter import limiter, estimate_prompt_tokens

# ---------------------------------------------------------------------------
# Answer schema default
# ---------------------------------------------------------------------------

def _empty_answer() -> dict[str, Any]:
    return {
        "answer": "Not found in the report",
        "numeric_value": None,
        "unit": None,
        "period": None,
        "scope": None,
        "status": "Not Found",
        "confidence": "Low",
        "page": None,
        "supporting_text": None,
        "explanation": "The LLM did not return a parseable response.",
        "other_values": [],
    }


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _parse_json_from_response(text: str) -> dict[str, Any]:
    """
    Extract and parse the first JSON object from an LLM response string.
    Handles cases where the model wraps the JSON in markdown code fences.
    """
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?", "", text).strip()

    # Find first { ... } block
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")

    # Find matching closing brace
    depth = 0
    end = -1
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise ValueError("Unmatched braces in JSON response")

    json_str = text[start:end + 1]
    return json.loads(json_str)


# ---------------------------------------------------------------------------
# Provider caller (Groq)
# ---------------------------------------------------------------------------

def _call_groq(prompt: str, model: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured. Please add it to .streamlit/secrets.toml or your environment.")

    model_name = model or "openai/gpt-oss-20b"
    if model_name == "gpt-oss-20b":
        model_name = "openai/gpt-oss-20b"
    elif model_name == "gpt-oss-120b":
        model_name = "openai/gpt-oss-120b"

    from groq import Groq
    client = Groq(api_key=api_key)

    try:
        resp = client.chat.completions.create(
            model=model_name,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        tokens_used = getattr(resp.usage, "total_tokens", 0) if hasattr(resp, "usage") and resp.usage else 0
        if tokens_used:
            limiter.record_usage(tokens_used)
        return resp.choices[0].message.content or ""
    except Exception:
        # Fallback without explicit response_format if model doesn't support it
        resp = client.chat.completions.create(
            model=model_name,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ],
        )
        tokens_used = getattr(resp.usage, "total_tokens", 0) if hasattr(resp, "usage") and resp.usage else 0
        if tokens_used:
            limiter.record_usage(tokens_used)
        return resp.choices[0].message.content or ""



import time as _time  # aliased to avoid shadowing


def _call_with_retry(fn, *args, max_retries: int = 3, **kwargs) -> str:
    """
    Call fn(*args, **kwargs) with exponential backoff on transient failures.
    Retries on RateLimitError, APIStatusError (429), or generic connection errors.
    """
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            exc_str = str(exc).lower()
            # Only retry on rate-limit / transient errors
            if any(kw in exc_str for kw in ("rate", "429", "timeout", "connection", "overloaded")):
                last_exc = exc
                if attempt < max_retries - 1:
                    _time.sleep(delay)
                    delay *= 2  # exponential backoff
            else:
                raise  # non-retryable error — propagate immediately
    raise last_exc  # type: ignore[misc]


def _call_llm(prompt: str) -> str:
    # Ensure token capacity before sending the request to keep usage under 7500 TPM
    est_tokens = estimate_prompt_tokens(prompt)
    limiter.wait_for_capacity(est_tokens)

    model = os.environ.get("LLM_MODEL", "")
    return _call_with_retry(_call_groq, prompt, model)



# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_answer(
    question: str,
    question_type: str,
    chunks: list,
) -> dict[str, Any]:
    """
    Send the question and retrieved chunks to the LLM.
    Returns a structured answer dict matching the output schema.
    """
    prompt = get_prompt(question_type, question, chunks)

    try:
        raw = _call_llm(prompt)
    except Exception as e:
        result = _empty_answer()
        result["explanation"] = f"LLM call failed: {e}"
        return result

    try:
        parsed = _parse_json_from_response(raw)
    except Exception as e:
        result = _empty_answer()
        result["explanation"] = f"JSON parse error: {e}. Raw response: {raw[:300]}"
        return result

    # Ensure all required keys exist with defaults
    defaults = _empty_answer()
    for key, default_val in defaults.items():
        parsed.setdefault(key, default_val)

    return parsed
