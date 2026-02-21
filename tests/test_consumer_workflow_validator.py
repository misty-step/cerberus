from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lib.consumer_workflow_validator import _comment_policy, _WORKFLOW_LOADER, validate_workflow_file


ROOT = Path(__file__).parent.parent


def _errors(findings):
    return [f for f in findings if f.level == "error"]


def _load_workflow(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=_WORKFLOW_LOADER)


def test_minimal_template_has_no_errors():
    findings, _ = validate_workflow_file(ROOT / "templates/consumer-workflow-minimal.yml")
    assert _errors(findings) == []


def test_missing_verdict_write_permission_is_error(tmp_path: Path):
    wf = tmp_path / "cerberus.yml"
    wf.write_text(
        """
name: Cerberus
on: pull_request
jobs:
  review:
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus@v2
        with:
          perspective: correctness
          github-token: ${{ secrets.GITHUB_TOKEN }}
          api-key: ${{ secrets.OPENROUTER_API_KEY }}
          post-comment: 'false'
  verdict:
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
""".lstrip()
    )

    findings, _ = validate_workflow_file(wf)
    assert any("pull-requests: write" in f.message for f in _errors(findings))


def test_missing_github_token_is_error(tmp_path: Path):
    wf = tmp_path / "cerberus.yml"
    wf.write_text(
        """
name: Cerberus
on: pull_request
jobs:
  review:
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus@v2
        with:
          perspective: correctness
          api-key: ${{ secrets.OPENROUTER_API_KEY }}
          post-comment: 'false'
""".lstrip()
    )

    findings, _ = validate_workflow_file(wf)
    assert any("with: github-token" in f.message for f in _errors(findings))


def test_comment_policy_default_never_does_not_require_pr_write(tmp_path: Path):
    wf = tmp_path / "cerberus.yml"
    wf.write_text(
        """
name: Cerberus
on: pull_request
jobs:
  review:
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus@v2
        with:
          perspective: correctness
          github-token: ${{ secrets.GITHUB_TOKEN }}
          api-key: ${{ secrets.OPENROUTER_API_KEY }}
""".lstrip()
    )

    findings, _ = validate_workflow_file(wf)
    assert _errors(findings) == []


@pytest.mark.parametrize("bad_yaml", ["on: [pull_request\n", "jobs: [\n"])
def test_invalid_yaml_is_error(tmp_path: Path, bad_yaml: str):
    wf = tmp_path / "broken.yml"
    wf.write_text(bad_yaml)
    findings, _ = validate_workflow_file(wf)
    assert _errors(findings) != []


def test_comment_policy_always_requires_pr_write(tmp_path: Path):
    wf = tmp_path / "cerberus.yml"
    wf.write_text(
        """
name: Cerberus
on: pull_request
jobs:
  review:
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus@v2
        with:
          perspective: correctness
          github-token: ${{ secrets.GITHUB_TOKEN }}
          api-key: ${{ secrets.OPENROUTER_API_KEY }}
          comment-policy: 'always'
""".lstrip()
    )

    findings, _ = validate_workflow_file(wf)
    assert any("comment-policy" in f.message and "pull-requests: write" in f.message for f in _errors(findings))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("never", ("never", False)),
        ("always", ("always", False)),
        ("non-pass", ("non-pass", False)),
        ("true", ("always", False)),
        ("false", ("never", False)),
        ("1", ("always", False)),
        ("0", ("never", False)),
        ("yes", ("always", False)),
        ("no", ("never", False)),
        ("on", ("always", False)),
        ("off", ("never", False)),
        ("", ("never", False)),
        ("wat", ("never", True)),
    ],
)
def test__comment_policy_parses_variants(value: str, expected: tuple[str, bool]):
    assert _comment_policy({"with": {"comment-policy": value}}) == expected


def test__comment_policy_falls_back_to_post_comment_when_comment_policy_unset():
    assert _comment_policy({"with": {"post-comment": "always"}}) == ("always", False)


def test__comment_policy_falls_back_to_post_comment_when_comment_policy_empty():
    assert _comment_policy({"with": {"comment-policy": "", "post-comment": "always"}}) == (
        "always",
        False,
    )


def test__comment_policy_comment_policy_wins_when_non_empty():
    assert _comment_policy({"with": {"comment-policy": "never", "post-comment": "always"}}) == (
        "never",
        False,
    )


@pytest.mark.parametrize(
    "path",
    [
        ROOT / ".github/workflows/cerberus.yml",
        ROOT / "templates/consumer-workflow-minimal.yml",
        ROOT / "templates/consumer-workflow.yml",
        ROOT / "templates/triage-workflow.yml",
    ],
)
def test_workflows_include_ready_for_review_and_draft_transitions(path: Path):
    wf = _load_workflow(path)
    types = wf["on"]["pull_request"]["types"]
    assert "ready_for_review" in types
    assert "converted_to_draft" in types


@pytest.mark.parametrize(
    "path",
    [
        ROOT / ".github/workflows/cerberus.yml",
        ROOT / "templates/consumer-workflow-minimal.yml",
        ROOT / "templates/consumer-workflow.yml",
        ROOT / "templates/triage-workflow.yml",
    ],
)
def test_workflows_have_skip_gate_job(path: Path):
    wf = _load_workflow(path)
    # TODO: tighten to preflight-only after minimal/triage templates are migrated (#208 follow-up)
    assert "draft-check" in wf["jobs"] or "preflight" in wf["jobs"]


# ---------------------------------------------------------------------------
# continue-on-error footgun (#219)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("uses", [
    "misty-step/cerberus@v2",
    "misty-step/cerberus/verdict@v2",
    "misty-step/cerberus/triage@v2",
])
def test_continue_on_error_true_emits_warning(tmp_path: Path, uses: str):
    """continue-on-error: true on a Cerberus step must surface a warning."""
    # Determine minimum required with keys so no unrelated errors fire
    with_block = "github-token: ${{ secrets.GITHUB_TOKEN }}"
    if uses.startswith("misty-step/cerberus@"):
        with_block += "\n          api-key: ${{ secrets.OPENROUTER_API_KEY }}"

    perms = """
    permissions:
      contents: write
      pull-requests: write"""

    wf = tmp_path / "cerberus.yml"
    wf.write_text(f"""
name: Cerberus
on: pull_request
jobs:
  cerberus:
{perms}
    runs-on: ubuntu-latest
    steps:
      - uses: {uses}
        continue-on-error: true
        with:
          {with_block}
""".lstrip())

    findings, _ = validate_workflow_file(wf)
    warnings = [f for f in findings if f.level == "warning"]
    assert any("continue-on-error" in f.message for f in warnings), (
        f"Expected a warning about continue-on-error for {uses!r}, got: {findings}"
    )


def test_continue_on_error_false_no_warning(tmp_path: Path):
    """continue-on-error: false is safe and must not trigger a warning."""
    wf = tmp_path / "cerberus.yml"
    wf.write_text("""
name: Cerberus
on: pull_request
jobs:
  cerberus:
    permissions:
      contents: write
      pull-requests: write
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        continue-on-error: false
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
""".lstrip())

    findings, _ = validate_workflow_file(wf)
    assert not any("continue-on-error" in f.message for f in findings)


def test_continue_on_error_absent_no_warning(tmp_path: Path):
    """No continue-on-error key at all must not trigger a warning."""
    wf = tmp_path / "cerberus.yml"
    wf.write_text("""
name: Cerberus
on: pull_request
jobs:
  cerberus:
    permissions:
      contents: write
      pull-requests: write
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
""".lstrip())

    findings, _ = validate_workflow_file(wf)
    assert not any("continue-on-error" in f.message for f in findings)


def test_continue_on_error_warning_includes_remediation(tmp_path: Path):
    """Warning message must include actionable remediation guidance."""
    wf = tmp_path / "cerberus.yml"
    wf.write_text("""
name: Cerberus
on: pull_request
jobs:
  cerberus:
    permissions:
      contents: write
      pull-requests: write
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        continue-on-error: true
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
""".lstrip())

    findings, _ = validate_workflow_file(wf)
    warning = next(f for f in findings if "continue-on-error" in f.message)
    # Must mention a concrete alternative
    assert any(kw in warning.message for kw in ("fail-on-skip", "triage", "fallback"))


# ---------------------------------------------------------------------------
# continue-on-error: expression-based (#219 gap 1)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expression", [
    "${{ inputs.allow_failure }}",
    "${{ vars.CONTINUE_ON_ERROR }}",
])
def test_continue_on_error_expression_step_emits_warning(tmp_path: Path, expression: str):
    """Expression-based continue-on-error on a step must warn (may resolve to true)."""
    wf = tmp_path / "cerberus.yml"
    wf.write_text(f"""
name: Cerberus
on: pull_request
jobs:
  cerberus:
    permissions:
      contents: write
      pull-requests: write
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        continue-on-error: '{expression}'
        with:
          github-token: ${{{{ secrets.GITHUB_TOKEN }}}}
""".lstrip())

    findings, _ = validate_workflow_file(wf)
    warnings = [f for f in findings if f.level == "warning"]
    assert any("continue-on-error" in f.message for f in warnings), (
        f"Expected a warning for expression {expression!r}, got: {findings}"
    )


# ---------------------------------------------------------------------------
# Job-level continue-on-error (#219 gap 2)
# ---------------------------------------------------------------------------

def test_job_continue_on_error_true_emits_warning(tmp_path: Path):
    """continue-on-error: true at the job level must surface a warning."""
    wf = tmp_path / "cerberus.yml"
    wf.write_text("""
name: Cerberus
on: pull_request
jobs:
  cerberus:
    continue-on-error: true
    permissions:
      contents: write
      pull-requests: write
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
""".lstrip())

    findings, _ = validate_workflow_file(wf)
    warnings = [f for f in findings if f.level == "warning"]
    assert any("continue-on-error" in f.message for f in warnings), (
        f"Expected a warning about job-level continue-on-error, got: {findings}"
    )


def test_job_continue_on_error_false_no_warning(tmp_path: Path):
    """continue-on-error: false at the job level must not trigger a warning."""
    wf = tmp_path / "cerberus.yml"
    wf.write_text("""
name: Cerberus
on: pull_request
jobs:
  cerberus:
    continue-on-error: false
    permissions:
      contents: write
      pull-requests: write
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
""".lstrip())

    findings, _ = validate_workflow_file(wf)
    assert not any("continue-on-error" in f.message for f in findings)


def test_job_continue_on_error_expression_emits_warning(tmp_path: Path):
    """Expression-based continue-on-error at the job level must warn."""
    wf = tmp_path / "cerberus.yml"
    wf.write_text("""
name: Cerberus
on: pull_request
jobs:
  cerberus:
    continue-on-error: '${{ inputs.allow_failure }}'
    permissions:
      contents: write
      pull-requests: write
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
""".lstrip())

    findings, _ = validate_workflow_file(wf)
    warnings = [f for f in findings if f.level == "warning"]
    assert any("continue-on-error" in f.message for f in warnings), (
        f"Expected a warning for expression-based job-level continue-on-error, got: {findings}"
    )
