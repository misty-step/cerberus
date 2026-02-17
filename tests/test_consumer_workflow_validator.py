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
def test_workflows_have_draft_check_job(path: Path):
    wf = _load_workflow(path)
    assert "draft-check" in wf["jobs"]
