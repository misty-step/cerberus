import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
ACTION_FILE = ROOT / "action.yml"
VERDICT_ACTION_FILE = ROOT / "verdict" / "action.yml"
POST_COMMENT_SCRIPT = ROOT / "scripts" / "post-comment.sh"
RUN_REVIEWER_SCRIPT = ROOT / "scripts" / "run-reviewer.sh"
COLLECT_OVERRIDES_SCRIPT = ROOT / "scripts" / "collect-overrides.py"
CONSUMER_WORKFLOW_TEMPLATE = ROOT / "templates" / "consumer-workflow-reusable.yml"
TRIAGE_WORKFLOW_TEMPLATE = ROOT / "templates" / "triage-workflow.yml"
REVIEW_PROMPT_TEMPLATE = ROOT / "templates" / "review-prompt.md"
README_FILE = ROOT / "README.md"


def test_verdict_action_uses_python_override_collection() -> None:
    content = VERDICT_ACTION_FILE.read_text()
    collector = COLLECT_OVERRIDES_SCRIPT.read_text()

    assert "scripts/collect-overrides.py" in content
    assert "--github-output \"$GITHUB_OUTPUT\"" in content
    assert "OVERRIDES=$(gh api" not in content
    assert "user.get(\"login\")" in collector


def test_verdict_action_uses_shared_upsert() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "scripts/lib/github.py" in content
    assert '--body-file "${CERBERUS_TMP}/verdict-comment.md"' in content
    assert "--marker" in content


def test_verdict_action_posts_inline_review_comments() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "scripts/post-verdict-review.py" in content
    assert '--verdict-json "${CERBERUS_TMP}/verdict.json"' in content
    assert '--body-file "${CERBERUS_TMP}/verdict-comment.md"' in content


def test_post_comment_uses_shared_upsert() -> None:
    content = POST_COMMENT_SCRIPT.read_text()

    assert "scripts/lib/github.py" in content
    assert "--body-file" in content
    assert "--marker" in content


def test_action_uses_api_key_fallback_validator() -> None:
    content = ACTION_FILE.read_text()

    assert "scripts/validate-inputs.sh" in content
    assert "CERBERUS_API_KEY" in content
    assert "OPENROUTER_API_KEY" in content
    match = re.search(r"api-key:\n(?:\s+.+\n)+", content)
    assert match is not None
    assert "required: false" in match.group(0)


def test_action_validates_perspective_from_defaults_config() -> None:
    content = ACTION_FILE.read_text()

    assert "scripts/validate-perspective.py" in content
    assert "--config \"$CERBERUS_ROOT/defaults/config.yml\"" in content
    assert "--perspective \"$PERSPECTIVE\"" in content


def test_action_pins_pi_install_version() -> None:
    content = ACTION_FILE.read_text()

    pi_match = re.search(r"pi-version:\n(?:\s+.+\n)+", content)
    legacy_match = re.search(r"opencode-version:\n(?:\s+.+\n)+", content)
    assert pi_match is not None
    assert legacy_match is not None
    assert "default: '0.55.0'" in pi_match.group(0)
    assert "default: ''" in legacy_match.group(0)
    assert "Invalid pi-version format" in content
    assert "Both 'pi-version' and deprecated 'opencode-version' were provided; using 'pi-version'." in content
    assert 'npm i -g "@mariozechner/pi-coding-agent@${resolved_version}"' in content
    assert "pip install pyyaml" in content


def test_action_reads_primary_model_file_when_present() -> None:
    content = ACTION_FILE.read_text()

    # Model metadata should prefer CERBERUS_TMP/<perspective>-primary-model written by run-reviewer.sh
    assert "PRIMARY_MODEL_FILE" in content
    assert "primary-model" in content


def test_action_reads_configured_model_file_when_present() -> None:
    content = ACTION_FILE.read_text()

    assert "CONFIGURED_MODEL_FILE" in content
    assert "configured-model" in content


def test_consumer_template_passes_key_via_input() -> None:
    content = CONSUMER_WORKFLOW_TEMPLATE.read_text()

    assert "api-key:" in content
    assert "CERBERUS_OPENROUTER_API_KEY" in content


def test_workflow_templates_use_current_major_version() -> None:
    consumer = CONSUMER_WORKFLOW_TEMPLATE.read_text()
    triage = TRIAGE_WORKFLOW_TEMPLATE.read_text()

    assert "@v1" not in consumer
    assert "@v1" not in triage

    # consumer-workflow-reusable.yml delegates to the reusable workflow on master.
    assert "misty-step/cerberus" in consumer
    assert "@master" in consumer

    assert "uses: misty-step/cerberus@master" in triage
    assert "uses: misty-step/cerberus/verdict@master" in triage
    assert "uses: misty-step/cerberus/triage@master" in triage


def test_readme_quick_start_uses_cerberus_openrouter_secret_name() -> None:
    content = README_FILE.read_text()

    assert "CERBERUS_OPENROUTER_API_KEY" in content
    assert "MOONSHOT_API_KEY" not in content


def test_permission_help_is_present_in_shared_module() -> None:
    github_module = ROOT / "scripts" / "lib" / "github.py"
    content = github_module.read_text()

    assert "pull-requests: write" in content


def test_verdict_action_avoids_heredoc_in_run_block() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "cat >&2 <<'EOF'" not in content


def test_verdict_action_uses_python_renderer_for_verdict_comment() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "scripts/render-verdict-comment.py" in content
    assert '--output "${CERBERUS_TMP}/verdict-comment.md"' in content


def test_verdict_action_does_not_use_sparse_checkout_dot() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "sparse-checkout: ." not in content


def test_fail_on_skip_is_wired_in_actions() -> None:
    verdict_content = VERDICT_ACTION_FILE.read_text()
    review_content = ACTION_FILE.read_text()

    assert "fail-on-skip:" in verdict_content
    assert "inputs.fail-on-skip" in verdict_content
    assert "FAIL_ON_SKIP" in verdict_content

    assert "fail-on-skip:" in review_content
    assert "inputs.fail-on-skip" in review_content
    assert "FAIL_ON_SKIP" in review_content


def test_skip_verdict_emits_warning_not_notice() -> None:
    """SKIP verdict without fail-on-skip should warn, not silently pass."""
    verdict_content = VERDICT_ACTION_FILE.read_text()

    assert '::warning::Cerberus Verdict: SKIP' in verdict_content
    assert '::notice::Cerberus Verdict: SKIP' not in verdict_content


def test_fail_on_skip_env_passed_to_render_step() -> None:
    """FAIL_ON_SKIP must be available to render-verdict-comment.py for advisory banner."""
    verdict_content = VERDICT_ACTION_FILE.read_text()

    # Verify FAIL_ON_SKIP is in the Post verdict step (before the render script call)
    post_verdict_idx = verdict_content.index("Post verdict")
    render_idx = verdict_content.index("render-verdict-comment.py")
    fail_on_skip_idx = verdict_content.index("FAIL_ON_SKIP: ${{ inputs.fail-on-skip }}")
    assert post_verdict_idx < fail_on_skip_idx < render_idx


def test_fail_on_verdict_is_wired_in_review_action() -> None:
    review_content = ACTION_FILE.read_text()

    assert "fail-on-verdict:" in review_content
    assert "inputs.fail-on-verdict" in review_content
    assert "FAIL_ON_VERDICT" in review_content
    assert 'if [ "$FAIL_ON_VERDICT" = "true" ]; then' in review_content
    assert 'echo "::error::${PERSPECTIVE} review verdict: FAIL"' in review_content
    assert 'echo "::notice::${PERSPECTIVE} review verdict: FAIL (reported to Cerberus)"' in review_content


def test_review_prompt_references_diff_file_placeholder() -> None:
    prompt_content = REVIEW_PROMPT_TEMPLATE.read_text()
    render_prompt_content = (ROOT / "scripts" / "render-review-prompt.py").read_text()

    assert "{{DIFF_FILE}}" in prompt_content
    assert "DIFF_FILE" in render_prompt_content
