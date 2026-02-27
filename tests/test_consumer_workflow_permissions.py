"""Regression tests for least-privilege permission split (#55).

Two consumer templates, two permission models:

1. consumer-workflow-reusable.yml (reusable workflow caller):
   - Single `review` job delegates to the Cerberus reusable workflow
   - Job-level permissions: contents: read + pull-requests: write
   - No workflow-level pull-requests: write

2. consumer-workflow-minimal.yml (decomposed pipeline):
   - Explicit review/verdict jobs with least-privilege per job
   - review jobs: read-only (no pull-requests: write)
   - verdict job: pull-requests: write
   - review jobs: comment-policy: 'never'
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
REUSABLE_CONSUMER = ROOT / "templates" / "consumer-workflow-reusable.yml"
DECOMPOSED_CONSUMER = ROOT / "templates" / "consumer-workflow-minimal.yml"
JOB_BOUNDARY = r"(?=^  [A-Za-z0-9_-]+:|\Z)"


# ---------------------------------------------------------------------------
# Reusable workflow consumer (consumer-workflow-reusable.yml)
# ---------------------------------------------------------------------------


def test_no_workflow_level_pull_requests_write():
    content = REUSABLE_CONSUMER.read_text()
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
        "use job-level permissions on the uses: job instead"
    )


def test_reusable_consumer_review_job_has_required_permissions():
    content = REUSABLE_CONSUMER.read_text()
    review_block = re.search(
        rf"^  review:\n(.*?){JOB_BOUNDARY}", content, re.MULTILINE | re.DOTALL
    )
    assert review_block is not None, "review job not found in consumer-workflow-reusable.yml"
    block = review_block.group(0)

    assert re.search(r"contents:\s*read", block), "review job must have contents: read"
    assert re.search(r"pull-requests:\s*write", block), (
        "review job calling the reusable workflow must have pull-requests: write "
        "(required for preflight and verdict jobs inside the reusable workflow)"
    )


# ---------------------------------------------------------------------------
# Decomposed pipeline consumer (consumer-workflow-minimal.yml)
# ---------------------------------------------------------------------------


def _read_decomposed():
    return DECOMPOSED_CONSUMER.read_text()


def _decomposed_review_wave_blocks(content: str):
    return list(
        re.finditer(
            rf"^  review-wave\d+:\n(.*?){JOB_BOUNDARY}", content, re.MULTILINE | re.DOTALL
        )
    )


def test_decomposed_review_job_has_read_only_permissions():
    content = _read_decomposed()
    review_blocks = _decomposed_review_wave_blocks(content)
    assert review_blocks, "review-wave jobs not found in consumer-workflow-minimal.yml"

    for review_block in review_blocks:
        block = review_block.group(0)
        assert re.search(r"contents:\s*read", block), "review-wave job must have contents: read"
        assert not re.search(r"pull-requests:\s*write", block), (
            "review-wave job must not have pull-requests: write"
        )


def test_decomposed_verdict_job_has_write_permissions():
    content = _read_decomposed()
    verdict_block = re.search(
        rf"^  verdict:\n(.*?){JOB_BOUNDARY}", content, re.MULTILINE | re.DOTALL
    )
    assert verdict_block is not None, "verdict job not found in consumer-workflow-minimal.yml"
    block = verdict_block.group(0)

    assert re.search(r"pull-requests:\s*write", block), (
        "verdict job must have pull-requests: write"
    )


def test_decomposed_review_job_disables_post_comment():
    content = _read_decomposed()
    review_blocks = _decomposed_review_wave_blocks(content)
    assert review_blocks, "review-wave jobs not found in consumer-workflow-minimal.yml"

    for review_block in review_blocks:
        block = review_block.group(0)
        # Either old post-comment: 'false' or new comment-policy: 'never' is acceptable
        has_old_style = re.search(r"post-comment:\s*['\"]?false['\"]?", block)
        has_new_style = re.search(r"comment-policy:\s*['\"]?never['\"]?", block)
        assert has_old_style or has_new_style, (
            "review-wave job must set comment-policy: 'never' "
            "(or legacy post-comment: 'false') — only verdict should post PR comments"
        )
