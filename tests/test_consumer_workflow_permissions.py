"""Regression tests for least-privilege permission split (#55).

The consumer workflow template must enforce:
- review jobs: read-only (no pull-requests: write)
- verdict job: pull-requests: write (only job that posts comments)
- review jobs: post-comment disabled (artifact-only output)
"""

import yaml
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONSUMER_WORKFLOW = ROOT / "templates" / "consumer-workflow.yml"


def _load_workflow():
    return yaml.safe_load(CONSUMER_WORKFLOW.read_text())


def test_no_workflow_level_pull_requests_write():
    wf = _load_workflow()
    top_perms = wf.get("permissions", {})
    assert top_perms.get("pull-requests") != "write", (
        "Workflow-level permissions must not grant pull-requests: write; "
        "use job-level permissions instead"
    )


def test_review_job_has_read_only_permissions():
    wf = _load_workflow()
    review_perms = wf["jobs"]["review"]["permissions"]
    assert review_perms["contents"] == "read"
    assert review_perms.get("pull-requests") in ("read", None), (
        "Review job must not have pull-requests: write"
    )


def test_verdict_job_has_write_permissions():
    wf = _load_workflow()
    verdict_perms = wf["jobs"]["verdict"]["permissions"]
    assert verdict_perms["pull-requests"] == "write"


def test_review_job_disables_post_comment():
    wf = _load_workflow()
    review_steps = wf["jobs"]["review"]["steps"]
    cerberus_step = next(
        s for s in review_steps if isinstance(s.get("uses", ""), str)
        and "misty-step/cerberus@" in s["uses"]
    )
    assert cerberus_step["with"]["post-comment"] == "false", (
        "Review job must set post-comment: 'false' — "
        "only the verdict job should post PR comments"
    )
