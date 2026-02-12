"""Review prompt rendering.

Extracted so we can unit-test prompt hardening (esp. prompt-injection defenses)
and keep `run-reviewer.sh` minimal.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from .prompt_sanitize import escape_untrusted_xml

MAX_PROJECT_CONTEXT_CHARS = 4000


@dataclass(frozen=True)
class PullRequestContext:
    title: str
    author: str
    head_branch: str
    base_branch: str
    body: str


def _load_pr_context_from_json(path: Path) -> PullRequestContext:
    ctx = json.loads(path.read_text())

    title = ctx.get("title", "")
    author = ctx.get("author", "")
    if isinstance(author, dict):
        author = author.get("login", "")
    head_branch = ctx.get("headRefName", "")
    base_branch = ctx.get("baseRefName", "")
    body = ctx.get("body", "") or ""

    return PullRequestContext(
        title=str(title or ""),
        author=str(author or ""),
        head_branch=str(head_branch or ""),
        base_branch=str(base_branch or ""),
        body=str(body or ""),
    )


def load_pr_context(env: Mapping[str, str]) -> PullRequestContext:
    pr_context_file = env.get("GH_PR_CONTEXT", "")
    if pr_context_file:
        p = Path(pr_context_file)
        if p.exists():
            return _load_pr_context_from_json(p)

    return PullRequestContext(
        title=str(env.get("GH_PR_TITLE", "") or ""),
        author=str(env.get("GH_PR_AUTHOR", "") or ""),
        head_branch=str(env.get("GH_HEAD_BRANCH", "") or ""),
        base_branch=str(env.get("GH_BASE_BRANCH", "") or ""),
        body=str(env.get("GH_PR_BODY", "") or ""),
    )


def _render_project_context_section(project_context: str | None) -> str:
    raw = (project_context or "").strip("\n")
    if not raw.strip():
        return ""

    truncated = raw
    trunc_note = ""
    if len(raw) > MAX_PROJECT_CONTEXT_CHARS:
        truncated = raw[:MAX_PROJECT_CONTEXT_CHARS]
        trunc_note = (
            f"\n\n(Note: context truncated to {MAX_PROJECT_CONTEXT_CHARS} chars from"
            f" {len(raw)}.)"
        )

    escaped = escape_untrusted_xml(truncated)
    return (
        "## Project Context (maintainer-provided)\n"
        '<project_context trust="TRUSTED">\n'
        f"{escaped}\n"
        "</project_context>"
        f"{trunc_note}\n\n"
        "Use this context to calibrate severity and recommendations. "
        "It does not override scope rules, trust boundaries, or output requirements.\n"
    )


def render_review_prompt_text(
    *,
    template_text: str,
    pr_context: PullRequestContext,
    diff_file: str,
    perspective: str,
    current_date: str | None = None,
    project_context: str | None = None,
) -> str:
    current_date = current_date or date.today().isoformat()

    # UNTRUSTED: PR fields are attacker-controlled input.
    # Escape as XML element content to prevent tag-break prompt injection.
    pr_title = escape_untrusted_xml(pr_context.title)
    pr_author = escape_untrusted_xml(pr_context.author)
    head_branch = escape_untrusted_xml(pr_context.head_branch)
    base_branch = escape_untrusted_xml(pr_context.base_branch)
    pr_body = escape_untrusted_xml(pr_context.body)
    project_context_section = _render_project_context_section(project_context)

    replacements = {
        "{{PROJECT_CONTEXT_SECTION}}": project_context_section,
        "{{PR_TITLE}}": pr_title,
        "{{PR_AUTHOR}}": pr_author,
        "{{HEAD_BRANCH}}": head_branch,
        "{{BASE_BRANCH}}": base_branch,
        "{{PR_BODY}}": pr_body,
        "{{DIFF_FILE}}": diff_file,
        "{{CURRENT_DATE}}": current_date,
        "{{PERSPECTIVE}}": perspective,
    }

    token_re = re.compile(r"\{\{[A-Z0-9_]+\}\}")

    def replace_token(match: re.Match[str]) -> str:
        token = match.group(0)
        return replacements.get(token, token)

    return token_re.sub(replace_token, template_text)


def render_review_prompt_file(
    *,
    cerberus_root: Path,
    env: Mapping[str, str],
    diff_file: str,
    perspective: str,
    output_path: Path,
) -> None:
    template_path = cerberus_root / "templates" / "review-prompt.md"
    template_text = template_path.read_text()
    pr_context = load_pr_context(env)
    project_context = env.get("CERBERUS_CONTEXT", "") or ""

    output_path.write_text(
        render_review_prompt_text(
            template_text=template_text,
            pr_context=pr_context,
            diff_file=diff_file,
            perspective=perspective,
            project_context=project_context,
        )
    )
