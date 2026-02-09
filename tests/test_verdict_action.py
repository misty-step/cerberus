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
    assert "OPENROUTER_API_KEY" in content
    match = re.search(r"api-key:\n(?:\s+.+\n)+", content)
    assert match is not None
    assert "required: false" in match.group(0)


def test_action_pins_opencode_install_version() -> None:
    content = ACTION_FILE.read_text()

    match = re.search(r"opencode-version:\n(?:\s+.+\n)+", content)
    assert match is not None
    assert "default: '1.1.49'" in match.group(0)
    assert "Invalid opencode-version format" in content
    assert 'npm i -g "opencode-ai@${OPENCODE_VERSION}"' in content
    assert "pip install" not in content


def test_consumer_template_passes_key_via_input() -> None:
    content = CONSUMER_WORKFLOW_TEMPLATE.read_text()

    assert "api-key: ${{ secrets.OPENROUTER_API_KEY }}" in content


def test_readme_quick_start_uses_openrouter_secret_name() -> None:
    content = README_FILE.read_text()

    assert "OPENROUTER_API_KEY" in content
    assert "MOONSHOT_API_KEY" not in content


def test_permission_help_is_present_in_comment_scripts() -> None:
    post_comment_content = POST_COMMENT_SCRIPT.read_text()
    verdict_content = VERDICT_ACTION_FILE.read_text()

    assert "pull-requests: write" in post_comment_content
    assert "pull-requests: write" in verdict_content


def test_verdict_action_avoids_heredoc_in_run_block() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "cat >&2 <<'EOF'" not in content


def test_verdict_action_uses_python_renderer_for_council_comment() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "scripts/render-council-comment.py" in content
    assert "--output /tmp/council-comment.md" in content


def test_verdict_action_does_not_use_sparse_checkout_dot() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "sparse-checkout: ." not in content


def test_review_prompt_includes_detected_stack_placeholder() -> None:
    prompt_content = REVIEW_PROMPT_TEMPLATE.read_text()
    run_reviewer_content = RUN_REVIEWER_SCRIPT.read_text()

    assert "{{PROJECT_STACK}}" in prompt_content
    assert '"{{PROJECT_STACK}}"' in run_reviewer_content
