"""Contract tests for github_read extension actions and payload shape."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_FILE = ROOT / "pi" / "extensions" / "github-read.ts"
TEXT = EXTENSION_FILE.read_text(encoding="utf-8")
EXPECTED_ACTIONS = {
    "get_pr",
    "get_pr_comments",
    "get_linked_issues",
    "get_issue",
    "search_issues",
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


def test_get_pr_contract() -> None:
    assert "`repos/${repo}/pulls/${prNumber}`" in TEXT


def test_get_pr_comments_contract() -> None:
    assert "`repos/${repo}/issues/${prNumber}/comments?per_page=${limit}`" in TEXT
    assert "`repos/${repo}/pulls/${prNumber}/comments?per_page=${limit}`" in TEXT
    assert "issue_comments: issueComments" in TEXT
    assert "review_comments: reviewComments" in TEXT


def test_get_linked_issues_contract() -> None:
    assert "closingIssuesReferences(first: ${limit})" in TEXT
    assert "number" in TEXT
    assert "title" in TEXT
    assert "url" in TEXT
    assert "state" in TEXT
    assert "body" in TEXT
    assert "const includeBodies = params.includeBodies !== false;" in TEXT
    assert "delete node.body;" in TEXT


def test_get_issue_contract() -> None:
    assert "`repos/${repo}/issues/${params.issueNumber}`" in TEXT


def test_search_issues_contract() -> None:
    assert '"search/issues"' in TEXT
    assert "`q=repo:${repo} ${query}`" in TEXT
    assert "`per_page=${limit}`" in TEXT


def test_error_payload_contract() -> None:
    assert "github_read error:" in TEXT
    assert "isError: true" in TEXT
