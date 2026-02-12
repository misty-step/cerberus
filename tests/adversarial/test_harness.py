"""Adversarial pattern harness.

Goal: keep a small catalog of attacker-style inputs and assert deterministic
invariants for Cerberus input handling (no network, no LLM calls).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from lib.review_prompt import PullRequestContext, render_review_prompt_text


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_TEXT = (ROOT / "templates" / "review-prompt.md").read_text()
PATTERNS = json.loads((Path(__file__).parent / "patterns.json").read_text())


def _render_prompt(inputs: dict[str, str]) -> str:
    ctx = PullRequestContext(
        title=inputs.get("pr_title", ""),
        author=inputs.get("pr_author", ""),
        head_branch=inputs.get("head_branch", ""),
        base_branch=inputs.get("base_branch", ""),
        body=inputs.get("pr_body", ""),
    )
    return render_review_prompt_text(
        template_text=TEMPLATE_TEXT,
        pr_context=ctx,
        diff_file="/tmp/pr.diff",
        perspective="security",
        current_date="2026-02-12",
    )


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.get("id", "unknown"))
def test_patterns(pattern: dict) -> None:
    assert isinstance(pattern, dict)
    assert "id" in pattern
    assert "inputs" in pattern
    assert "assertions" in pattern

    rendered_prompt = _render_prompt(pattern["inputs"])

    for a in pattern["assertions"]:
        surface = a.get("surface")
        kind = a.get("kind")
        value = a.get("value")

        if surface != "rendered_prompt":
            raise AssertionError(f"{pattern['id']}: unknown surface: {surface}")
        if kind not in ("contains", "not_contains", "regex"):
            raise AssertionError(f"{pattern['id']}: unknown assertion kind: {kind}")

        if kind == "contains":
            assert value in rendered_prompt, f"{pattern['id']}: missing: {value}"
        elif kind == "not_contains":
            assert value not in rendered_prompt, f"{pattern['id']}: found: {value}"
        else:
            assert re.search(value, rendered_prompt), f"{pattern['id']}: no match: {value}"
