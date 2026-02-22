"""Regression tests for least-privilege permission split (#55).

The consumer workflow template must enforce:
- review jobs: read-only (no pull-requests: write)
- verdict job: pull-requests: write (only job that posts comments)
- review jobs: comment-policy: 'never' (artifact-only output, single verdict comment)
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONSUMER_WORKFLOW = ROOT / "templates" / "consumer-workflow.yml"


def _read_workflow():
    return CONSUMER_WORKFLOW.read_text()


def test_no_workflow_level_pull_requests_write():
    content = _read_workflow()
    # A top-level permissions block sits before the jobs: key and outside any
    # job indentation.  Match "permissions:" at column 0 followed by a
    # pull-requests: write line at indent 2.
    top_perms = re.search(
        r"^permissions:\s*\n(?:\s{2}\S.*\n)*?\s{2}pull-requests:\s*write",
        content,
        re.MULTILINE,
    )
    assert top_perms is None, (
        "Workflow-level permissions must not grant pull-requests: write; "
        "use job-level permissions instead"
    )


def test_review_job_has_read_only_permissions():
    content = _read_workflow()
    # Extract the review job block (from "  review:" to the next job at same
    # indentation or end of file).
    review_block = re.search(
        r"^  review:\n(.*?)(?=^  \w+:|\Z)", content, re.MULTILINE | re.DOTALL
    )
    assert review_block is not None, "review job not found in template"
    block = review_block.group(0)

    assert re.search(r"contents:\s*read", block), "review job must have contents: read"
    assert not re.search(r"pull-requests:\s*write", block), (
        "review job must not have pull-requests: write"
    )


def test_verdict_job_has_write_permissions():
    content = _read_workflow()
    verdict_block = re.search(
        r"^  verdict:\n(.*?)(?=^  \w+:|\Z)", content, re.MULTILINE | re.DOTALL
    )
    assert verdict_block is not None, "verdict job not found in template"
    block = verdict_block.group(0)

    assert re.search(r"pull-requests:\s*write", block), (
        "verdict job must have pull-requests: write"
    )


def test_review_job_disables_post_comment():
    content = _read_workflow()
    review_block = re.search(
        r"^  review:\n(.*?)(?=^  \w+:|\Z)", content, re.MULTILINE | re.DOTALL
    )
    assert review_block is not None, "review job not found in template"
    block = review_block.group(0)

    # Either old post-comment: 'false' or new comment-policy: 'never' is acceptable
    has_old_style = re.search(r"post-comment:\s*['\"]?false['\"]?", block)
    has_new_style = re.search(r"comment-policy:\s*['\"]?never['\"]?", block)
    assert has_old_style or has_new_style, (
        "review job must set comment-policy: 'never' (or legacy post-comment: 'false') — "
        "only the verdict job should post PR comments"
    )
