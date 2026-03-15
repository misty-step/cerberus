"""Tests for api/dispatch.sh preflight logic.

Validates that the thin action correctly skips fork PRs, draft PRs,
and missing credentials before dispatching to the API.
"""

import os
import subprocess
import tempfile

DISPATCH_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "api", "dispatch.sh")


def run_dispatch(env_overrides, expect_fail=False):
    """Run dispatch.sh with given env and capture output."""
    env = {
        "HEAD_REPO": "org/repo",
        "BASE_REPO": "org/repo",
        "IS_DRAFT": "false",
        "CERBERUS_API_KEY": "test-key",
        "CERBERUS_URL": "http://localhost:9999",
        "PR_NUMBER": "42",
        "HEAD_SHA": "abc123def456",
        "GITHUB_TOKEN": "ghp_test",
        "GITHUB_OUTPUT": "",
        "PATH": os.environ.get("PATH", ""),
    }
    env.update(env_overrides)

    # Use a temp file for GITHUB_OUTPUT
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        env["GITHUB_OUTPUT"] = f.name

    try:
        result = subprocess.run(
            ["bash", DISPATCH_SCRIPT],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        with open(env["GITHUB_OUTPUT"]) as f:
            outputs = dict(
                line.split("=", 1) for line in f.read().strip().split("\n") if "=" in line
            )
        return result, outputs
    except subprocess.TimeoutExpired:
        return None, {}
    finally:
        os.unlink(env["GITHUB_OUTPUT"])


class TestPreflightSkips:
    def test_skips_fork_pr(self):
        result, outputs = run_dispatch({"HEAD_REPO": "fork/repo"})
        assert result.returncode == 0
        assert outputs.get("verdict") == "SKIP"

    def test_skips_draft_pr(self):
        result, outputs = run_dispatch({"IS_DRAFT": "true"})
        assert result.returncode == 0
        assert outputs.get("verdict") == "SKIP"

    def test_fails_missing_api_key(self):
        result, outputs = run_dispatch({"CERBERUS_API_KEY": ""})
        assert result.returncode == 1
        assert outputs.get("verdict") == "SKIP"

    def test_fails_missing_url(self):
        result, outputs = run_dispatch({"CERBERUS_URL": ""})
        assert result.returncode == 1

    def test_fails_missing_pr_number(self):
        result, outputs = run_dispatch({"PR_NUMBER": ""})
        assert result.returncode == 1

    def test_fails_missing_head_sha(self):
        result, outputs = run_dispatch({"HEAD_SHA": ""})
        assert result.returncode == 1


class TestDispatchAttempt:
    def test_dispatch_fails_on_unreachable_api(self):
        """When the API is unreachable, dispatch fails gracefully."""
        result, outputs = run_dispatch(
            {"CERBERUS_URL": "http://localhost:1"},
            expect_fail=True,
        )
        # curl will fail to connect — script should exit non-zero
        assert result.returncode != 0
