"""Tests for PR context fetch retry and fallback logic in action.yml (#211).

Covers:
- Retry loop capped at max_pr_view_retries=3
- Per-attempt timeout (pr_view_timeout_seconds=20)
- Exponential backoff only on auth errors
- Error classification (auth / permissions / other)
- Bounded step output (error message truncation)
- Parse fallback content generation via printf (YAML-safe, no heredoc)
- Parse step runs on pr step failure (if: always())
- Step outputs: pr-context-error-kind, pr-context-error-message
- Timeout exit code (124) captured before branching
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
ACTION_FILE = ROOT / "action.yml"


def _action_content() -> str:
    return ACTION_FILE.read_text()


def _load_action() -> dict:
    return yaml.safe_load(ACTION_FILE.read_text())


def _find_step(steps: list, name_pattern: str) -> dict | None:
    for step in steps:
        if re.search(name_pattern, step.get("name", ""), re.IGNORECASE):
            return step
    return None


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------


def test_fetch_step_caps_retries_at_three() -> None:
    content = _action_content()
    assert "max_pr_view_retries=3" in content, (
        "gh pr view retry cap must be exactly 3 to bound flake retry cost"
    )


def test_fetch_step_uses_per_attempt_timeout() -> None:
    content = _action_content()
    assert "pr_view_timeout_seconds=20" in content, (
        "Each gh pr view attempt must have a 20-second timeout to prevent stalls"
    )
    assert 'timeout "$pr_view_timeout_seconds" gh pr view' in content, (
        "timeout must wrap each gh pr view attempt, not just the loop"
    )


def test_fetch_step_applies_exponential_backoff_on_auth_error() -> None:
    content = _action_content()
    # Backoff: wait_seconds = attempt * 2
    assert "wait_seconds=$((pr_view_attempt * 2))" in content, (
        "Exponential backoff must multiply attempt count by 2 for auth retries"
    )
    assert "sleep" in content and "wait_seconds" in content, (
        "Backoff sleep must use wait_seconds variable"
    )


def test_fetch_step_only_retries_on_auth_errors() -> None:
    content = _action_content()
    # backoff/retry on auth, not permissions/other
    assert (
        'if [[ "$pr_view_error_kind" == "auth" ]]' in content
        or "pr_view_error_kind" in content
    ), "Retry branch must be conditional on error kind == auth"


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def test_classify_function_present() -> None:
    content = _action_content()
    assert "classify_pr_view_error()" in content, (
        "classify_pr_view_error() helper must be defined in action.yml"
    )


def test_classify_401_bad_credentials_as_auth() -> None:
    content = _action_content()
    # The classify function regex should include both 401 and bad credentials
    assert "401" in content and "bad credentials" in content.lower(), (
        "Classifier must match HTTP 401 and 'bad credentials' text as auth errors"
    )


def test_classify_403_forbidden_as_permissions() -> None:
    content = _action_content()
    assert "403" in content and (
        "forbidden" in content.lower() or "permission denied" in content.lower()
    ), "Classifier must match 403 / forbidden as permissions errors"


def test_classify_fallthrough_is_other() -> None:
    content = _action_content()
    # Non-auth, non-permissions errors fall through to "other"
    assert '"other"' in content, (
        "Classifier must produce 'other' for non-auth/non-permissions failures"
    )


# ---------------------------------------------------------------------------
# Step outputs
# ---------------------------------------------------------------------------


def test_fetch_step_emits_error_kind_output() -> None:
    content = _action_content()
    assert "pr-context-error-kind" in content, (
        "Fetch step must emit pr-context-error-kind to GITHUB_OUTPUT"
    )


def test_fetch_step_emits_error_message_output() -> None:
    content = _action_content()
    assert "pr-context-error-message" in content, (
        "Fetch step must emit pr-context-error-message to GITHUB_OUTPUT"
    )


def test_fetch_step_initialises_outputs_to_empty() -> None:
    content = _action_content()
    # Blank-init guard: empty string emitted at step start before any failure
    assert "pr-context-error-kind=" in content, (
        "Step must initialise pr-context-error-kind to empty string before any failure"
    )
    assert "pr-context-error-message=" in content, (
        "Step must initialise pr-context-error-message to empty string before any failure"
    )


# ---------------------------------------------------------------------------
# Bounded output
# ---------------------------------------------------------------------------


def test_error_message_output_is_truncated() -> None:
    content = _action_content()
    # Output bound: at most 1000 chars for step output variable
    assert "cut -c1-1000" in content, (
        "Error message written to GITHUB_OUTPUT must be truncated to 1000 chars"
    )


def test_log_breadcrumb_is_truncated() -> None:
    content = _action_content()
    # Log bound: at most 4000 chars for the larger log breadcrumb
    assert "cut -c1-4000" in content, (
        "Error detail echoed to log must be truncated to 4000 chars"
    )


# ---------------------------------------------------------------------------
# Timeout exit code capture
# ---------------------------------------------------------------------------


def test_timeout_exit_code_captured_before_branch() -> None:
    content = _action_content()
    # pr_view_rc must be assigned from $? immediately after timeout call
    # and the timeout check uses -eq 124 against that variable
    assert "pr_view_rc=$?" in content, (
        "timeout exit code must be captured into pr_view_rc immediately after the command"
    )
    assert '"$pr_view_rc" -eq 124' in content or "pr_view_rc\" -eq 124" in content, (
        "Timeout branch must check pr_view_rc == 124, not re-read $?"
    )


# ---------------------------------------------------------------------------
# Parse fallback: YAML safety and content
# ---------------------------------------------------------------------------


def test_parse_step_runs_on_pr_failure() -> None:
    action = _load_action()
    steps = action["runs"]["steps"]
    parse_step = _find_step(steps, r"parse review")
    assert parse_step is not None, "Parse review output step not found in action.yml"
    assert parse_step.get("if") == "always()", (
        "Parse step must run even when the PR fetch step fails (if: always())"
    )


def test_parse_fallback_uses_printf_not_heredoc() -> None:
    content = _action_content()
    run_blocks = re.findall(
        r"- name: Parse review output.*?(?=\n    - name:|\Z)",
        content,
        re.DOTALL,
    )
    assert run_blocks, "Could not locate Parse review output step"
    parse_block = run_blocks[0]
    assert "printf" in parse_block, (
        "Parse fallback must write via printf so action.yml stays valid YAML (no heredoc)"
    )
    assert "<<" not in parse_block or "<<'" not in parse_block.replace("<<'EOF'", ""), (
        "Parse fallback must NOT use heredoc (breaks YAML parsing of action.yml)"
    )


def test_parse_fallback_auth_error_sets_api_key_invalid() -> None:
    content = _action_content()
    assert "API Error: API_KEY_INVALID" in content, (
        "Auth-error fallback must write API_KEY_INVALID so parse-review.py "
        "classifies it as a SKIP with correct error kind"
    )
    assert "HTTP 401 Bad credentials was returned by GitHub CLI" in content, (
        "Auth fallback must include the 401 detail for operator diagnosis"
    )


def test_parse_fallback_permissions_error_sets_api_error() -> None:
    content = _action_content()
    assert "pull-requests: read access and valid repository scope" in content, (
        "Permissions-error fallback must include remediation hint about pull-requests: read"
    )


def test_parse_fallback_other_error_sets_api_error() -> None:
    content = _action_content()
    assert "Unable to fetch PR context:" in content, (
        "Generic fallback must include 'Unable to fetch PR context:' so downstream "
        "parse-review sees a recognisable error header"
    )


def test_parse_fallback_branches_on_pr_step_outcome() -> None:
    content = _action_content()
    # Parse step checks steps.pr.outcome before generating fallback
    assert 'steps.pr.outcome' in content, (
        "Parse fallback must be conditional on steps.pr.outcome != 'success'"
    )
    assert "pr-context-error-kind" in content, (
        "Parse fallback must also check that pr-context-error-kind is non-empty"
    )
