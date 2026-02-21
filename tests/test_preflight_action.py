from pathlib import Path

ROOT = Path(__file__).parent.parent
PREFLIGHT_ACTION_FILE = ROOT / "preflight" / "action.yml"


def test_preflight_action_exists_and_exposes_contract() -> None:
    content = PREFLIGHT_ACTION_FILE.read_text()

    assert 'name: "Cerberus Preflight"' in content
    assert "Detect skip conditions" in content
    assert "outputs:" in content
    assert "should_run:" in content
    assert "skip_reason:" in content
    assert "<!-- cerberus:preflight -->" in content
    assert "scripts/lib/github.py" in content


def test_preflight_action_checks_fork_then_draft_then_api_key() -> None:
    content = PREFLIGHT_ACTION_FILE.read_text()

    assert 'if [ "$HEAD_REPO" != "$BASE_REPO" ]' in content
    assert 'echo "should_run=false" >> "$GITHUB_OUTPUT"' in content
    assert 'echo "skip_reason=fork" >> "$GITHUB_OUTPUT"' in content

    assert 'if [ "$IS_DRAFT" = "true" ]' in content
    assert 'echo "skip_reason=draft" >> "$GITHUB_OUTPUT"' in content

    assert 'if [ -z "$API_KEY" ]' in content
    assert 'echo "skip_reason=missing_api_key" >> "$GITHUB_OUTPUT"' in content

    assert 'echo "should_run=true" >> "$GITHUB_OUTPUT"' in content
    assert 'echo "skip_reason=none" >> "$GITHUB_OUTPUT"' in content

    # Verify check order: fork → draft → API key (matches function name)
    fork_idx = content.index('if [ "$HEAD_REPO" != "$BASE_REPO" ]')
    draft_idx = content.index('if [ "$IS_DRAFT" = "true" ]')
    api_key_idx = content.index('if [ -z "$API_KEY" ]')
    assert fork_idx < draft_idx < api_key_idx, "Checks must be in order: fork → draft → API key"


def test_preflight_action_limits_draft_comment_events_and_handles_failures() -> None:
    content = PREFLIGHT_ACTION_FILE.read_text()

    assert 'if [ "$ACTION" = "opened" ] || [ "$ACTION" = "converted_to_draft" ]' in content
    assert 'if [ "$POST_COMMENT" = "true" ] && [ -n "$GH_TOKEN" ] && [ -n "$PR_NUMBER" ]' in content
    assert '|| echo "::warning::Failed to post preflight comment"' in content
