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
    assert "mktemp -d" in content, "Temp files must use mktemp, not hardcoded /tmp/"


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


def test_preflight_action_uses_single_parameterized_comment_function() -> None:
    """Verify comment logic is consolidated, not duplicated per skip reason."""
    content = PREFLIGHT_ACTION_FILE.read_text()

    assert content.count("write_skip_comment") >= 3, (
        "Expected write_skip_comment definition + at least 2 call sites"
    )
    # No leftover per-reason comment functions
    assert "write_draft_comment" not in content
    assert "write_missing_key_comment" not in content


def test_preflight_action_comment_guards_require_token_and_pr_number() -> None:
    """Both draft and missing-key paths must check POST_COMMENT, GH_TOKEN, and PR_NUMBER."""
    content = PREFLIGHT_ACTION_FILE.read_text()

    # Count guard patterns — should appear in both draft and missing-key branches
    guard = '[ "$POST_COMMENT" = "true" ] && [ -n "$GH_TOKEN" ] && [ -n "$PR_NUMBER" ]'
    assert content.count(guard) == 2, (
        "Both skip-reason branches must guard comment posting on POST_COMMENT + GH_TOKEN + PR_NUMBER"
    )


def test_preflight_action_no_hardcoded_tmp_paths() -> None:
    """Regression guard: #234 established mktemp convention; no hardcoded /tmp/ paths."""
    content = PREFLIGHT_ACTION_FILE.read_text()

    import re
    # Match /tmp/ used as a file path (not inside a comment or the mktemp command itself)
    hardcoded = re.findall(r'"/tmp/[^"]*"', content)
    assert hardcoded == [], f"Hardcoded /tmp/ paths found: {hardcoded}. Use mktemp -d instead."


def test_preflight_action_emits_all_skip_reasons() -> None:
    """Every documented skip_reason value must appear in the action output logic."""
    content = PREFLIGHT_ACTION_FILE.read_text()

    for reason in ("fork", "draft", "missing_api_key", "none"):
        assert f'skip_reason={reason}' in content, f"Missing skip_reason={reason} in output"


def test_preflight_action_temp_dir_cleanup() -> None:
    """Temp directory must be cleaned up via trap on EXIT."""
    content = PREFLIGHT_ACTION_FILE.read_text()

    assert "trap" in content and "EXIT" in content, "Must trap EXIT to clean up temp dir"
