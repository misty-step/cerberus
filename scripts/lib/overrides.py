"""Cerberus override comment parsing and authorization.

Extracts override detection, SHA validation, and actor authorization
into a reusable module shared by aggregate-verdict.py and any future
consumers (e.g. triage, status page).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Override:
    """A parsed and validated council override."""

    actor: str
    sha: str
    reason: str


POLICY_STRICTNESS: dict[str, int] = {
    "pr_author": 0,
    "write_access": 1,
    "maintainers_only": 2,
}


def parse_override(raw: str | None, head_sha: str | None) -> Override | None:
    """Parse a single override comment JSON into an Override.

    Returns None if the input is missing, malformed, or fails SHA validation.
    """
    if not raw or raw.strip() in {"", "null", "None"}:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None

    actor = obj.get("actor") or obj.get("author") or "unknown"
    sha = obj.get("sha")
    reason = obj.get("reason")

    body = obj.get("body")
    if body:
        lines = [line.strip() for line in body.splitlines()]
        command_line = next(
            (l for l in lines if l.startswith("/cerberus override") or l.startswith("/council override")),
            "",
        )
        if command_line:
            match = re.search(r"sha=([0-9a-fA-F]+)", command_line)
            if match:
                sha = sha or match.group(1)
        for line in lines:
            if line.lower().startswith("reason:"):
                reason = reason or line.split(":", 1)[1].strip()
        if not reason:
            remainder = [
                l for l in lines
                if l and not l.startswith("/cerberus override") and not l.startswith("/council override")
            ]
            if remainder:
                reason = " ".join(remainder)

    if not sha or not reason:
        return None

    if len(sha) < 7:
        return None

    if head_sha and not head_sha.startswith(sha):
        return None

    return Override(actor=actor, sha=sha, reason=reason)


def validate_actor(
    actor: str,
    policy: str,
    pr_author: str | None,
    actor_permission: str | None = None,
) -> bool:
    """Check whether an actor is authorized under the given policy."""
    if policy == "pr_author":
        return bool(pr_author) and actor.lower() == pr_author.lower()
    if policy == "write_access":
        return actor_permission in ("write", "maintain", "admin")
    if policy == "maintainers_only":
        return actor_permission in ("maintain", "admin")
    return False


def select_override(
    comments_raw: str | None,
    head_sha: str | None,
    policy: str,
    pr_author: str | None,
    actor_permissions: dict[str, str] | None = None,
) -> Override | None:
    """Select the first authorized override from a chronological comment list.

    Iterates comments in order, parses each, validates the actor against the
    given policy, and returns the first that passes all checks.
    """
    if not comments_raw or comments_raw.strip() in ("", "null", "None", "[]"):
        return None

    try:
        parsed_input = json.loads(comments_raw)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed_input, dict):
        parsed_input = [parsed_input]

    if not isinstance(parsed_input, list) or not parsed_input:
        return None

    permissions = actor_permissions or {}

    for i, comment in enumerate(parsed_input):
        raw = json.dumps(comment)
        parsed = parse_override(raw, head_sha)
        actor_name = comment.get("actor") or comment.get("author") or "unknown"
        if parsed is None:
            print(
                f"aggregate-verdict: override {i + 1}/{len(parsed_input)} "
                f"from '{actor_name}': skipped (invalid or SHA mismatch)",
                file=sys.stderr,
            )
            continue

        permission = permissions.get(parsed.actor)
        if validate_actor(parsed.actor, policy, pr_author, permission):
            print(
                f"aggregate-verdict: override {i + 1}/{len(parsed_input)} "
                f"from '{parsed.actor}': authorized (policy={policy})",
                file=sys.stderr,
            )
            return parsed
        else:
            print(
                f"aggregate-verdict: override {i + 1}/{len(parsed_input)} "
                f"from '{parsed.actor}': rejected by policy '{policy}'",
                file=sys.stderr,
            )

    return None


def determine_effective_policy(
    verdicts: list[dict],
    reviewer_policies: dict[str, str],
    global_policy: str,
) -> str:
    """Pick the strictest override policy among failing reviewers."""
    failing = [v for v in verdicts if v.get("verdict") == "FAIL"]
    if not failing:
        return global_policy

    strictest = global_policy
    for v in failing:
        reviewer = v.get("reviewer", "")
        policy = reviewer_policies.get(reviewer, global_policy)
        if POLICY_STRICTNESS.get(policy, -1) > POLICY_STRICTNESS.get(strictest, -1):
            strictest = policy
    return strictest
