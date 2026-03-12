"""Tests for PR context bootstrap and fallback wiring in action.yml.

Covers:
- Bootstrap fetch delegated to helper script
- Explicit repo/PR plumbing into the helper
- Bounded step output (error message truncation)
- Parse fallback content generation via printf (YAML-safe, no heredoc)
- Parse step runs on pr step failure (if: always())
- Step outputs: pr-context-error-kind, pr-context-error-message
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
# Bootstrap helper wiring
# ---------------------------------------------------------------------------


def test_fetch_step_uses_bootstrap_helper_script() -> None:
    content = _action_content()
    assert 'scripts/fetch-pr-bootstrap.py' in content, (
        "Fetch step must delegate PR bootstrap to the helper script"
    )


def test_fetch_step_passes_explicit_repo_and_pr_to_helper() -> None:
    content = _action_content()
    assert 'REPO: ${{ github.repository }}' in content, (
        "Fetch step must expose github.repository as REPO for helper invocation"
    )
    assert 'PR_NUMBER: ${{ github.event.pull_request.number }}' in content, (
        "Fetch step must expose the PR number for helper invocation"
    )
    assert '--repo "$REPO"' in content, (
        "Bootstrap helper must receive the explicit repository"
    )
    assert '--pr "$PR_NUMBER"' in content, (
        "Bootstrap helper must receive the pull request number"
    )


def test_fetch_step_passes_output_paths_to_helper() -> None:
    content = _action_content()
    assert '--diff-file "$CERBERUS_TMP/pr.diff"' in content, (
        "Fetch step must pass the diff output path to the helper"
    )
    assert '--pr-context-file "$CERBERUS_TMP/pr-context.json"' in content, (
        "Fetch step must pass the PR context output path to the helper"
    )
    assert '--result-file "$CERBERUS_TMP/pr-bootstrap-result.json"' in content, (
        "Fetch step must pass a structured result path to the helper"
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
# Result-file handling
# ---------------------------------------------------------------------------


def test_fetch_step_reads_error_kind_from_result_file() -> None:
    content = _action_content()
    assert "pr-bootstrap-result.json" in content, (
        "Fetch step must read helper failures from the structured result file"
    )
    assert "pr-context-error-kind" in content, (
        "Fetch step must map helper failure kind into pr-context-error-kind"
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
