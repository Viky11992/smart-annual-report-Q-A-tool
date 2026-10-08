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
# Provider-specific callers
# ---------------------------------------------------------------------------

def _call_groq(prompt: str, model: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set.")

    model_name = model or "openai/gpt-oss-20b"
    if model_name == "gpt-oss-20b":
        model_name = "openai/gpt-oss-20b"
    elif model_name == "gpt-oss-120b":
        model_name = "openai/gpt-oss-120b"

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except ImportError:
        from openai import OpenAI
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
        )

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
    except Exception:
        # Fallback without explicit response_format if model/client doesn't support it
        resp = client.chat.completions.create(
            model=model_name,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ],
        )
    return resp.choices[0].message.content or ""


def _call_anthropic(prompt: str, model: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model or "claude-3-5-sonnet-20241022",
        max_tokens=2048,
        temperature=0,
        system=SYSTEM_MESSAGE,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _call_openai(prompt: str, model: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model=model or "gpt-4o",
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content or ""


def _call_gemini(prompt: str, model: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    m = genai.GenerativeModel(
        model_name=model or "gemini-1.5-pro",
        system_instruction=SYSTEM_MESSAGE,
    )
    resp = m.generate_content(
        prompt,
        generation_config={"temperature": 0},
    )
    return resp.text


def _call_llm(prompt: str) -> str:
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()
    model = os.environ.get("LLM_MODEL", "")
    if provider == "groq":
        return _call_groq(prompt, model)
    elif provider == "anthropic":
        return _call_anthropic(prompt, model)
    elif provider == "openai":
        return _call_openai(prompt, model)
    elif provider == "gemini":
        return _call_gemini(prompt, model)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


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
