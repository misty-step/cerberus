#!/usr/bin/env python3
"""Cerberus triage runtime.

This script is intentionally deterministic:
- It reads verdict output/comments and produces a diagnosis comment.
- It can optionally run a configured fix command and push a `[triage]` commit.
- It enforces circuit breakers to prevent infinite loops.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lib.github import upsert_pr_comment

VALID_MODES = {"off", "diagnose", "fix"}
VERDICT_MARKER = "cerberus:verdict"
TRIAGE_MARKER = "cerberus:triage"
TRIAGE_COMMAND = "/cerberus triage"
CERBERUS_TMP = Path(os.environ.get("CERBERUS_TMP", tempfile.gettempdir()))


def trusted_login() -> str:
    """Trusted login."""
    return os.environ.get("CERBERUS_BOT_LOGIN", "github-actions[bot]").strip().lower()


def comment_login(comment: dict) -> str:
    """Comment login."""
    user = comment.get("user")
    if isinstance(user, dict):
        login = user.get("login")
        if isinstance(login, str):
            return login.strip().lower()
    return ""


def is_trusted_comment(comment: dict, trusted: str) -> bool:
    """Is trusted comment."""
    return comment_login(comment) == trusted


def fail(message: str, code: int = 2) -> None:
    """Fail."""
    print(f"triage: {message}", file=sys.stderr)
    sys.exit(code)


def run(
    argv: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run."""
    result = subprocess.run(argv, check=False, capture_output=capture, text=text)
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "(no stderr)"
        fail(f"command failed ({result.returncode}): {' '.join(argv)}\n{stderr}")
    return result


def gh_json(args: list[str]) -> object:
    """Gh json."""
    result = run(["gh", "api", *args])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"gh api returned invalid JSON: {exc}")


def ensure_mode(value: str) -> str:
    """Ensure mode."""
    mode = value.strip().lower()
    if mode not in VALID_MODES:
        fail(f"invalid mode '{value}'. expected one of: {', '.join(sorted(VALID_MODES))}")
    return mode


def extract_verdict(body: str) -> str | None:
    """Extract cerberus verdict from comment body."""
    match = re.search(r"(?:Council|Cerberus) Verdict:\s*(PASS|WARN|FAIL|SKIP)\b", body, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def parse_triage_command_mode(command_body: str, default_mode: str) -> str:
    """Parse triage command mode."""
    lower = command_body.lower()
    if TRIAGE_COMMAND not in lower:
        return default_mode
    match = re.search(r"\bmode=(off|diagnose|fix)\b", lower)
    return match.group(1) if match else default_mode


def has_triage_commit_tag(message: str) -> bool:
    """Has triage commit tag."""
    return "[triage]" in message.lower()


def count_attempts_for_sha(comments: list[dict], head_sha: str, trusted: str) -> int:
    """Count attempts for sha."""
    count = 0
    for comment in comments:
        if not is_trusted_comment(comment, trusted):
            continue
        body = str(comment.get("body", ""))
        match = re.search(r"cerberus:triage sha=([0-9a-fA-F]+)", body)
        if not match:
            continue
        marker_sha = match.group(1)
        if head_sha.startswith(marker_sha):
            count += 1
    return count


def parse_iso8601(value: str) -> datetime:
    """Parse iso8601."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def should_schedule_pr(
    *,
    verdict: str | None,
    verdict_updated_at: str | None,
    attempts_for_sha: int,
    max_attempts: int,
    stale_hours: int,
    now: datetime,
) -> bool:
    """Should schedule pr."""
    if verdict != "FAIL":
        return False
    if verdict_updated_at is None:
        return False
    if attempts_for_sha >= max_attempts:
        return False
    updated_at = parse_iso8601(verdict_updated_at)
    return now - updated_at >= timedelta(hours=stale_hours)


def find_latest_verdict_comment(comments: list[dict], trusted: str) -> dict | None:
    """Find latest verdict comment."""
    verdict_comments = [
        c for c in comments if is_trusted_comment(c, trusted) and VERDICT_MARKER in str(c.get("body", ""))
    ]
    if not verdict_comments:
        return None
    return max(verdict_comments, key=lambda c: str(c.get("updated_at", "")))


def write_output(status: str, attempted: bool, reason: str, processed: int) -> None:
    """Write output."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as fh:
        fh.write(f"status={status}\n")
        fh.write(f"attempted={'true' if attempted else 'false'}\n")
        fh.write(f"reason={reason}\n")
        fh.write(f"processed={processed}\n")


def get_event() -> tuple[str, dict]:
    """Get event."""
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_name:
        fail("GITHUB_EVENT_NAME is required")
    if event_path and Path(event_path).exists():
        try:
            return event_name, json.loads(Path(event_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"unable to read event payload: {exc}")
    return event_name, {}


def select_targets(event_name: str, event: dict, default_mode: str) -> list[tuple[int, str, str]]:
    """Return list of (pr_number, mode, trigger)."""
    if event_name == "pull_request":
        pr = event.get("pull_request", {})
        number = pr.get("number")
        if isinstance(number, int):
            return [(number, default_mode, "automatic")]
        return []

    if event_name == "issue_comment":
        issue = event.get("issue", {})
        if not issue.get("pull_request"):
            return []
        body = str(event.get("comment", {}).get("body", ""))
        if not body.strip().lower().startswith(TRIAGE_COMMAND):
            return []
        number = issue.get("number")
        if isinstance(number, int):
            mode = parse_triage_command_mode(body, default_mode)
            return [(number, mode, "manual")]
        return []

    if event_name in {"schedule", "workflow_dispatch"}:
        # Pull list of open PRs and evaluate them with schedule policy.
        pulls = gh_json([f"repos/{os.environ['GITHUB_REPOSITORY']}/pulls?state=open&per_page=50"])
        if not isinstance(pulls, list):
            return []
        targets: list[tuple[int, str, str]] = []
        for pull in pulls:
            number = pull.get("number")
            if isinstance(number, int):
                targets.append((number, default_mode, "scheduled"))
        return targets

    return []


def tail(text: str, max_lines: int = 12) -> str:
    """Tail."""
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:]) if lines else ""


def post_triage_comment(
    *,
    repo: str,
    pr_number: int,
    comments: list[dict],
    head_sha: str,
    run_id: str,
    mode: str,
    trigger: str,
    verdict: str | None,
    outcome: str,
    diagnosis: str,
    details: str,
) -> None:
    """Post triage comment."""
    short_sha = head_sha[:12]
    marker = f"<!-- {TRIAGE_MARKER} sha={short_sha} run={run_id} -->"
    emoji = {
        "diagnosed": "🩺",
        "fixed": "✅",
        "fix_failed": "⚠️",
        "no_changes": "ℹ️",
        "skipped": "⏭️",
    }.get(outcome, "🩺")

    body = (
        f"## {emoji} Cerberus Triage: {outcome}\n\n"
        f"- Trigger: `{trigger}`\n"
        f"- Mode: `{mode}`\n"
        f"- Cerberus verdict: `{verdict or 'unknown'}`\n"
        f"- Head SHA: `{short_sha}`\n\n"
        f"### Diagnosis\n{diagnosis}\n\n"
        f"### Attempt Details\n{details}\n\n"
        f"{marker}\n"
    )

    comment_file = CERBERUS_TMP / "cerberus-triage-comment.md"
    comment_file.write_text(body, encoding="utf-8")

    upsert_pr_comment(
        repo=repo,
        pr_number=pr_number,
        marker=marker,
        body_file=str(comment_file),
        comments=comments,
    )


def gather_diagnosis(verdict_body: str | None) -> str:
    """Gather diagnosis."""
    if not verdict_body:
        return "- Cerberus verdict comment not found; cannot extract detailed findings."
    lines = [line.strip() for line in verdict_body.splitlines() if line.strip()]
    interesting = []
    for line in lines:
        if line.startswith("##"):
            continue
        if line.startswith("---"):
            continue
        if line.startswith("*Cerberus Council*") or line.startswith("*Cerberus*") or line.startswith("*Cerberus ("):
            continue
        interesting.append(line)
    if not interesting:
        return "- Cerberus verdict comment found but summary section was empty."
    return "- " + "\n- ".join(interesting[:6])


def fix_mode_block_reason(*, mode: str, trigger: str, repo: str, head_repo_name: str, git_exists: bool) -> str | None:
    """Fix mode block reason."""
    if mode != "fix":
        return None
    if trigger != "automatic":
        return "Fix mode is limited to automatic pull_request runs. Falling back to diagnosis."
    if repo != head_repo_name:
        return "Head branch comes from a fork; skipping fix push for safety."
    if not git_exists:
        return "No git checkout available in workspace; cannot apply fix."
    return None


def run_fix_command(command: str) -> tuple[str, str]:
    """Run fix command."""
    if not command.strip():
        return "no_changes", "No fix command configured (`fix-command` input is empty)."

    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = (result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")
    combined = combined.strip()

    if result.returncode != 0:
        detail = "Fix command failed.\n\n```text\n" + tail(combined) + "\n```"
        return "fix_failed", detail

    status = run(["git", "status", "--porcelain"], check=True).stdout.strip()
    if not status:
        detail = "Fix command completed but produced no file changes."
        return "no_changes", detail

    # Ensure bot identity before commit.
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", "[triage] auto-fix from Cerberus"])
    commit_sha = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    detail = "Applied and committed fixes.\n\n- Commit: `" + commit_sha + "`"
    return "fixed", detail


class RunResult:
    """Data class for Run Result."""
    def __init__(self, status: str, attempted: bool, reason: str) -> None:
        self.status = status
        self.attempted = attempted
        self.reason = reason


def triage_pr(
    *,
    repo: str,
    pr_number: int,
    mode: str,
    trigger: str,
    max_attempts: int,
    stale_hours: int,
    run_id: str,
    now: datetime,
) -> RunResult:
    """Triage pr."""
    pull = gh_json([f"repos/{repo}/pulls/{pr_number}"])
    if not isinstance(pull, dict):
        return RunResult("skipped", False, f"pr_{pr_number}_not_found")

    head = pull.get("head", {})
    head_sha = str(head.get("sha", ""))
    head_ref = str(head.get("ref", ""))
    head_repo_name = str(head.get("repo", {}).get("full_name", ""))
    if not head_sha:
        return RunResult("skipped", False, f"pr_{pr_number}_missing_sha")

    comments_obj = gh_json([f"repos/{repo}/issues/{pr_number}/comments?per_page=100"])
    comments = comments_obj if isinstance(comments_obj, list) else []
    trusted = trusted_login()
    latest_verdict = find_latest_verdict_comment(comments, trusted)
    verdict_body = str(latest_verdict.get("body", "")) if latest_verdict else None
    verdict = extract_verdict(verdict_body or "")
    attempts = count_attempts_for_sha(comments, head_sha, trusted)

    if trigger == "scheduled":
        updated_at = str(latest_verdict.get("updated_at")) if latest_verdict else None
        if not should_schedule_pr(
            verdict=verdict,
            verdict_updated_at=updated_at,
            attempts_for_sha=attempts,
            max_attempts=max_attempts,
            stale_hours=stale_hours,
            now=now,
        ):
            return RunResult("skipped", False, f"pr_{pr_number}_schedule_policy")
    else:
        if verdict != "FAIL":
            return RunResult("skipped", False, f"pr_{pr_number}_verdict_{(verdict or 'missing').lower()}")

    if attempts >= max_attempts:
        return RunResult("skipped", False, f"pr_{pr_number}_attempt_limit")

    commit_obj = gh_json([f"repos/{repo}/commits/{head_sha}"])
    message = str(commit_obj.get("commit", {}).get("message", ""))
    if has_triage_commit_tag(message):
        return RunResult("skipped", False, f"pr_{pr_number}_triage_commit")

    diagnosis = gather_diagnosis(verdict_body)
    fix_command = os.environ.get("TRIAGE_FIX_COMMAND", "")
    outcome = "diagnosed"
    details = "Diagnosis completed. No code changes requested in current mode."
    attempted = True

    block_reason = fix_mode_block_reason(
        mode=mode,
        trigger=trigger,
        repo=repo,
        head_repo_name=head_repo_name,
        git_exists=Path(".git").exists(),
    )
    if block_reason:
        details = block_reason
    elif mode == "fix":
        outcome, details = run_fix_command(fix_command)
        if outcome == "fixed":
            push_result = subprocess.run(
                ["git", "push", "origin", f"HEAD:{head_ref}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if push_result.returncode != 0:
                # Keep local commit for post-mortem visibility in runner logs.
                outcome = "fix_failed"
                details = (
                    "Fix commit created locally but push failed.\n\n```text\n"
                    + tail((push_result.stderr or "") + "\n" + (push_result.stdout or ""))
                    + "\n```"
                )

    post_triage_comment(
        repo=repo,
        pr_number=pr_number,
        comments=comments,
        head_sha=head_sha,
        run_id=run_id,
        mode=mode,
        trigger=trigger,
        verdict=verdict,
        outcome=outcome,
        diagnosis=diagnosis,
        details=details,
    )
    return RunResult(outcome, attempted, f"pr_{pr_number}_{outcome}")


def main() -> None:
    """Main."""
    mode = ensure_mode(os.environ.get("TRIAGE_MODE", "off"))
    if os.environ.get("CERBERUS_TRIAGE", "").strip().lower() == "off":
        mode = "off"

    if mode == "off":
        write_output("skipped", False, "mode_off", 0)
        print("triage: disabled (mode=off)")
        return

    if not os.environ.get("GITHUB_REPOSITORY"):
        fail("GITHUB_REPOSITORY is required")

    max_attempts = int(os.environ.get("TRIAGE_MAX_ATTEMPTS", "1"))
    stale_hours = int(os.environ.get("TRIAGE_STALE_HOURS", "24"))
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    event_name, event = get_event()
    targets = select_targets(event_name, event, mode)

    if not targets:
        write_output("skipped", False, "no_targets", 0)
        print("triage: no matching targets for this event")
        return

    now = datetime.now(UTC)
    repo = os.environ["GITHUB_REPOSITORY"]
    attempted = False
    processed = 0
    last_status = "skipped"
    last_reason = "no_attempts"

    for pr_number, target_mode, trigger in targets:
        result = triage_pr(
            repo=repo,
            pr_number=pr_number,
            mode=target_mode,
            trigger=trigger,
            max_attempts=max_attempts,
            stale_hours=stale_hours,
            run_id=run_id,
            now=now,
        )
        processed += 1
        attempted = attempted or result.attempted
        last_status = result.status
        last_reason = result.reason
        print(f"triage: pr#{pr_number}: {result.reason}")

    write_output(last_status, attempted, last_reason, processed)


if __name__ == "__main__":
    main()
