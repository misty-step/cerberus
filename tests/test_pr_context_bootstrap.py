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


def _fetch_step() -> dict:
    action = _load_action()
    steps = action["runs"]["steps"]
    fetch_step = _find_step(steps, r"fetch pr context")
    assert fetch_step is not None, "Fetch PR context step not found in action.yml"
    return fetch_step


# ---------------------------------------------------------------------------
# Bootstrap helper wiring
# ---------------------------------------------------------------------------


def test_fetch_step_uses_bootstrap_helper_script() -> None:
    fetch_step = _fetch_step()
    assert 'scripts/fetch-pr-bootstrap.py' in fetch_step["run"], (
        "Fetch step must delegate PR bootstrap to the helper script"
    )


def test_fetch_step_passes_explicit_repo_and_pr_to_helper() -> None:
    fetch_step = _fetch_step()
    fetch_env = fetch_step["env"]
    fetch_run = fetch_step["run"]
    assert fetch_env["REPO"] == "${{ github.repository }}", (
        "Fetch step must expose github.repository as REPO for helper invocation"
    )
    assert fetch_env["PR_NUMBER"] == "${{ github.event.pull_request.number }}", (
        "Fetch step must expose the PR number for helper invocation"
    )
    assert '--repo "$REPO"' in fetch_run, (
        "Bootstrap helper must receive the explicit repository"
    )
    assert '--pr "$PR_NUMBER"' in fetch_run, (
        "Bootstrap helper must receive the pull request number"
    )


def test_fetch_step_passes_output_paths_to_helper() -> None:
    fetch_run = _fetch_step()["run"]
    assert '--diff-file "$CERBERUS_TMP/pr.diff"' in fetch_run, (
        "Fetch step must pass the diff output path to the helper"
    )
    assert '--pr-context-file "$CERBERUS_TMP/pr-context.json"' in fetch_run, (
        "Fetch step must pass the PR context output path to the helper"
    )
    assert '--result-file "$CERBERUS_TMP/pr-bootstrap-result.json"' in fetch_run, (
        "Fetch step must pass a structured result path to the helper"
    )


# ---------------------------------------------------------------------------
# Step outputs
# ---------------------------------------------------------------------------


def test_fetch_step_emits_error_kind_output() -> None:
    fetch_run = _fetch_step()["run"]
    assert "pr-context-error-kind" in fetch_run, (
        "Fetch step must emit pr-context-error-kind to GITHUB_OUTPUT"
    )


def test_fetch_step_emits_error_message_output() -> None:
    fetch_run = _fetch_step()["run"]
    assert "pr-context-error-message" in fetch_run, (
        "Fetch step must emit pr-context-error-message to GITHUB_OUTPUT"
    )


def test_fetch_step_initialises_outputs_to_empty() -> None:
    fetch_run = _fetch_step()["run"]
    # Blank-init guard: empty string emitted at step start before any failure
    assert "pr-context-error-kind=" in fetch_run, (
        "Step must initialise pr-context-error-kind to empty string before any failure"
    )
    assert "pr-context-error-message=" in fetch_run, (
        "Step must initialise pr-context-error-message to empty string before any failure"
    )


# ---------------------------------------------------------------------------
# Bounded output
# ---------------------------------------------------------------------------


def test_error_message_output_is_truncated() -> None:
    fetch_run = _fetch_step()["run"]
    # Output bound: at most 1000 chars for step output variable
    assert "cut -c1-1000" in fetch_run, (
        "Error message written to GITHUB_OUTPUT must be truncated to 1000 chars"
    )


def test_log_breadcrumb_is_truncated() -> None:
    fetch_run = _fetch_step()["run"]
    # Log bound: at most 4000 chars for the larger log breadcrumb
    assert "cut -c1-4000" in fetch_run, (
        "Error detail echoed to log must be truncated to 4000 chars"
    )


# ---------------------------------------------------------------------------
# Result-file handling
# ---------------------------------------------------------------------------


def test_fetch_step_reads_error_kind_from_result_file() -> None:
    fetch_run = _fetch_step()["run"]
    assert "pr-bootstrap-result.json" in fetch_run, (
        "Fetch step must read helper failures from the structured result file"
    )
    assert "pr-context-error-kind" in fetch_run, (
        "Fetch step must map helper failure kind into pr-context-error-kind"
    )


def test_fetch_step_handles_missing_result_file() -> None:
    fetch_run = _fetch_step()["run"]
    assert 'if [[ -f "$CERBERUS_TMP/pr-bootstrap-result.json" ]]; then' in fetch_run, (
        "Fetch step must guard reads from the structured result file"
    )
    assert 'pr_view_error_text="Bootstrap helper failed before writing pr-bootstrap-result.json."' in fetch_run, (
        "Fetch step must preserve a diagnostic fallback when the helper exits before writing the result file"
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
