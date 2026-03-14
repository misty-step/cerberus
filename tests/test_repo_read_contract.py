"""Contract tests for repo_read extension actions and payload shape."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_FILE = ROOT / "pi" / "extensions" / "repo-read.ts"
TEXT = EXTENSION_FILE.read_text(encoding="utf-8")
EXPECTED_ACTIONS = {
    "list_changed_files",
    "read_file",
    "read_diff",
    "search_repo",
}


def _declared_actions() -> set[str]:
    match = re.search(r"StringEnum\(\[(.*?)\] as const\)", TEXT, flags=re.DOTALL)
    assert match, "Missing StringEnum action declaration"
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


def test_declares_exact_action_set() -> None:
    assert _declared_actions() == EXPECTED_ACTIONS


def test_has_control_flow_branch_per_action() -> None:
    for action in EXPECTED_ACTIONS:
        assert f'params.action === "{action}"' in TEXT


def test_success_payload_contract_is_consistent_across_actions() -> None:
    payload_content_line = 'content: [{ type: "text", text: JSON.stringify(payload, null, 2) }]'
    assert TEXT.count(payload_content_line) == len(EXPECTED_ACTIONS)
    assert TEXT.count("details: payload,") >= len(EXPECTED_ACTIONS)


def test_contract_requires_review_run_env() -> None:
    assert 'throw new Error("Missing CERBERUS_REVIEW_RUN")' in TEXT
    assert "CERBERUS_REVIEW_RUN must include diff_file and workspace_root" in TEXT


def test_read_file_contract_is_bounded_and_repo_relative() -> None:
    assert "repository-relative" in TEXT
    assert "path escapes workspace root" in TEXT
    assert "read_file may return at most " in TEXT


def test_list_changed_files_and_diff_contract_use_diff_artifact() -> None:
    assert "parseChangedFiles(readTextFile(reviewRun.diff_file))" in TEXT
    assert 'action === "list_changed_files"' in TEXT
    assert 'action === "read_diff"' in TEXT


def test_search_repo_contract_requires_query_and_path_prefix_guardrails() -> None:
    assert 'throw new Error("query is required for search_repo")' in TEXT
    assert 'pathPrefix' in TEXT
    assert "IGNORED_DIRECTORIES" in TEXT


def test_error_payload_contract() -> None:
    assert "repo_read error:" in TEXT
    assert "isError: true" in TEXT
