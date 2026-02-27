#!/usr/bin/env python3
"""Extract structured verdict from reviewer scratchpad via OpenRouter structured outputs.

Called by run-reviewer.py after the Pi agentic loop completes. Reads the scratchpad
and/or stdout file, makes one OpenRouter chat completion with response_format: json_schema,
and writes the structured verdict JSON to stdout.

Usage: extract-verdict.py <scratchpad_file> <perspective> [<model>]

Environment:
    CERBERUS_OPENROUTER_API_KEY or OPENROUTER_API_KEY: required
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default extraction model — confirmed to support response_format: json_schema on OpenRouter.
EXTRACTION_MODEL = "openrouter/moonshotai/kimi-k2.5"

# Models that emit reasoning traces or have known structured-output incompatibilities.
# These get silently rerouted to EXTRACTION_MODEL for the extraction step.
_UNSUPPORTED_MODELS: frozenset[str] = frozenset({
    "openrouter/x-ai/grok-code-fast-1",
    "x-ai/grok-code-fast-1",
})

# Verdict JSON schema for response_format: json_schema enforcement.
VERDICT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "WARN", "FAIL", "SKIP"]},
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["critical", "major", "minor", "info"]},
                    "category": {"type": "string"},
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "evidence": {"type": "string"},
                    "suggestion_verified": {"type": "boolean"},
                },
                "required": [
                    "severity", "category", "file", "line",
                    "title", "description", "suggestion",
                ],
                "additionalProperties": False,
            },
        },
        "stats": {
            "type": "object",
            "properties": {
                "files_reviewed": {"type": "integer"},
                "files_with_issues": {"type": "integer"},
                "critical": {"type": "integer"},
                "major": {"type": "integer"},
                "minor": {"type": "integer"},
                "info": {"type": "integer"},
            },
            "required": [
                "files_reviewed", "files_with_issues",
                "critical", "major", "minor", "info",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["verdict", "confidence", "summary", "findings", "stats"],
    "additionalProperties": False,
}


def _resolve_api_key() -> str:
    return (
        os.environ.get("CERBERUS_OPENROUTER_API_KEY", "").strip()
        or os.environ.get("OPENROUTER_API_KEY", "").strip()
    )


def _api_model_id(model: str) -> str:
    """Strip openrouter/ prefix for the API call."""
    if model.startswith("openrouter/"):
        return model[len("openrouter/"):]
    return model


def extract_verdict(
    content: str,
    perspective: str,
    model: str,
    api_key: str,
) -> dict:
    """Call OpenRouter with structured output to extract verdict JSON from review content."""
    api_model = _api_model_id(model)

    system_prompt = (
        "You are a code review formatter. Given reviewer analysis notes, produce the verdict JSON object. "
        "Include all findings from the notes. Do not add commentary or markdown."
    )
    user_prompt = (
        f"# Code Review Notes ({perspective})\n\n"
        f"{content}\n\n"
        "Extract the verdict from these notes as structured JSON."
    )

    payload = {
        "model": api_model,
        "temperature": 0.0,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "cerberus_verdict",
                "strict": True,
                "schema": VERDICT_SCHEMA,
            },
        },
    }

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/misty-step/cerberus",
            "X-Title": "Cerberus Verdict Extractor",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"request failed: {exc}") from exc

    try:
        content_str = body["choices"][0]["message"]["content"]
        return json.loads(content_str)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"unexpected response shape: {exc}") from exc


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: extract-verdict.py <scratchpad_file> <perspective> [<model>]",
            file=sys.stderr,
        )
        return 2

    scratchpad_file = Path(argv[0])
    perspective = argv[1]
    model = argv[2] if len(argv) > 2 else EXTRACTION_MODEL

    api_key = _resolve_api_key()
    if not api_key:
        print("extract-verdict: no API key (set CERBERUS_OPENROUTER_API_KEY)", file=sys.stderr)
        return 1

    if not scratchpad_file.exists() or scratchpad_file.stat().st_size == 0:
        print(f"extract-verdict: no content in {scratchpad_file}", file=sys.stderr)
        return 1

    content = scratchpad_file.read_text(encoding="utf-8", errors="replace")

    # Reroute models known to be incompatible with structured outputs.
    if model in _UNSUPPORTED_MODELS:
        print(
            f"extract-verdict: {model!r} doesn't support structured outputs; "
            f"using {EXTRACTION_MODEL}",
            file=sys.stderr,
        )
        model = EXTRACTION_MODEL

    try:
        verdict = extract_verdict(content, perspective, model, api_key)
    except RuntimeError as exc:
        print(f"extract-verdict: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(verdict, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
