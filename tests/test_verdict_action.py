import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
ACTION_FILE = ROOT / "action.yml"
VERDICT_ACTION_FILE = ROOT / "verdict" / "action.yml"
POST_COMMENT_SCRIPT = ROOT / "scripts" / "post-comment.sh"
RUN_REVIEWER_SCRIPT = ROOT / "scripts" / "run-reviewer.sh"
CONSUMER_WORKFLOW_TEMPLATE = ROOT / "templates" / "consumer-workflow.yml"
REVIEW_PROMPT_TEMPLATE = ROOT / "templates" / "review-prompt.md"
README_FILE = ROOT / "README.md"


def test_override_query_uses_rest_user_login() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert re.search(r"actor:\s*\.user\.login", content)


def test_verdict_action_updates_comment_with_typed_file_field() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "-X PATCH -F body=@/tmp/council-comment.md" in content
    assert "-X PATCH -f body=\"$(cat /tmp/council-comment.md)\"" not in content


def test_post_comment_updates_comment_with_typed_file_field() -> None:
    content = POST_COMMENT_SCRIPT.read_text()

    assert "-X PATCH -F body=@\"$comment_file\"" in content
    assert "-X PATCH -f body=\"$(cat \"$comment_file\")\"" not in content


def test_action_uses_api_key_fallback_validator() -> None:
    content = ACTION_FILE.read_text()

    assert "scripts/validate-inputs.sh" in content
    assert "CERBERUS_API_KEY" in content
    assert "ANTHROPIC_API_KEY" in content
    match = re.search(r"kimi-api-key:\n(?:\s+.+\n)+", content)
    assert match is not None
    assert "required: false" in match.group(0)


def test_consumer_template_uses_single_secret_env_fallback() -> None:
    content = CONSUMER_WORKFLOW_TEMPLATE.read_text()

    assert "CERBERUS_API_KEY: ${{ secrets.CERBERUS_API_KEY || secrets.ANTHROPIC_API_KEY }}" in content
    assert "kimi-api-key:" not in content


def test_readme_quick_start_uses_cerberus_secret_name() -> None:
    content = README_FILE.read_text()

    assert "CERBERUS_API_KEY" in content
    assert "MOONSHOT_API_KEY" not in content


def test_permission_help_is_present_in_comment_scripts() -> None:
    post_comment_content = POST_COMMENT_SCRIPT.read_text()
    verdict_content = VERDICT_ACTION_FILE.read_text()

    assert "pull-requests: write" in post_comment_content
    assert "pull-requests: write" in verdict_content


def test_verdict_action_avoids_heredoc_in_run_block() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "cat >&2 <<'EOF'" not in content


def test_verdict_action_does_not_use_sparse_checkout_dot() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "sparse-checkout: ." not in content


def test_review_prompt_includes_detected_stack_placeholder() -> None:
    prompt_content = REVIEW_PROMPT_TEMPLATE.read_text()
    run_reviewer_content = RUN_REVIEWER_SCRIPT.read_text()

    assert "{{PROJECT_STACK}}" in prompt_content
    assert '"{{PROJECT_STACK}}"' in run_reviewer_content
