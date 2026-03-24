"""Tests for api/dispatch.sh preflight and polling logic.

Validates that the thin action correctly skips fork PRs, draft PRs,
and missing credentials before dispatching to the API, and that the
polling loop handles status transitions, timeouts, and verdicts.
"""

import json
import os
import subprocess
import tempfile
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

DISPATCH_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "api", "dispatch.sh")


def run_dispatch(env_overrides, expect_fail=False, subprocess_timeout=5):
    """Run dispatch.sh with given env and capture output."""
    env = {
        "HEAD_REPO": "org/repo",
        "BASE_REPO": "org/repo",
        "IS_DRAFT": "false",
        "CERBERUS_API_KEY": "test-key",
        "CERBERUS_URL": "http://localhost:9999",
        "PR_NUMBER": "42",
        "HEAD_SHA": "abc123def456",
        "GITHUB_TOKEN": "test-token-fixture",
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
            timeout=subprocess_timeout,
        )
        with open(env["GITHUB_OUTPUT"]) as f:
            outputs = dict(
                line.split("=", 1) for line in f.read().strip().split("\n") if "=" in line
            )
        return result, outputs
    except subprocess.TimeoutExpired as exc:
        raise AssertionError("dispatch.sh timed out after 5s") from exc
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

    def test_fails_non_numeric_timeout(self):
        result, outputs = run_dispatch({"CERBERUS_TIMEOUT": "abc"})
        assert result.returncode == 1
        assert outputs.get("verdict") == "SKIP"
        assert "review-id" in outputs

    def test_fails_negative_timeout(self):
        result, outputs = run_dispatch({"CERBERUS_TIMEOUT": "-1"})
        assert result.returncode == 1
        assert outputs.get("verdict") == "SKIP"

    def test_fails_zero_poll_interval(self):
        result, outputs = run_dispatch({"CERBERUS_POLL_INTERVAL": "0"})
        assert result.returncode == 1
        assert outputs.get("verdict") == "SKIP"

    def test_fails_non_numeric_poll_interval(self):
        result, outputs = run_dispatch({"CERBERUS_POLL_INTERVAL": "abc"})
        assert result.returncode == 1
        assert outputs.get("verdict") == "SKIP"


class TestDispatchAttempt:
    def test_dispatch_fails_on_unreachable_api(self):
        """When the API is unreachable, dispatch fails gracefully."""
        result, outputs = run_dispatch(
            {"CERBERUS_URL": "http://localhost:1"},
            expect_fail=True,
        )
        # curl will fail to connect — script should exit non-zero
        assert result.returncode != 0

    def test_dispatch_payload_omits_or_includes_github_token(self):
        requests = []

        result, _outputs = _run_with_mock(
            [(200, {"status": "completed", "aggregated_verdict": {"verdict": "PASS"}})],
            requests=requests,
        )
        assert result.returncode == 0
        assert requests[0]["github_token"] == "test-token-fixture"

        requests = []

        result, _outputs = _run_with_mock(
            [(200, {"status": "completed", "aggregated_verdict": {"verdict": "PASS"}})],
            extra_env={"GITHUB_TOKEN": ""},
            requests=requests,
        )
        assert result.returncode == 0
        assert "github_token" not in requests[0]


# --- Mock API for polling tests ---


def _make_handler(responses, requests=None):
    """Build a request handler that replays canned responses in order.

    `responses` is a list of (status_code, body_dict) tuples.
    POST /api/reviews always returns 202 with a review_id.
    GET  /api/reviews/:id pops from the list.
    """
    call_count = {"poll": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # suppress request logs

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))

            if requests is not None:
                requests.append(json.loads(body or "{}"))

            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"review_id": 1, "status": "queued"}).encode())

        def do_GET(self):
            idx = min(call_count["poll"], len(responses) - 1)
            code, body = responses[idx]
            call_count["poll"] += 1
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    return Handler


def _run_with_mock(responses, extra_env=None, timeout=20, requests=None):
    """Start a mock HTTP server, run dispatch.sh against it, return (result, outputs)."""
    handler = _make_handler(responses, requests=requests)
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()

    env_overrides = {
        "CERBERUS_URL": f"http://127.0.0.1:{port}",
        "CERBERUS_POLL_INTERVAL": "1",
        "CERBERUS_TIMEOUT": "10",
    }
    if extra_env:
        env_overrides.update(extra_env)

    try:
        return run_dispatch(env_overrides, subprocess_timeout=timeout)
    finally:
        server.shutdown()


class TestPollingLoop:
    def test_completed_pass_verdict(self):
        """Completed review with PASS exits 0."""
        result, outputs = _run_with_mock([
            (200, {"status": "queued"}),
            (200, {"status": "running"}),
            (200, {"status": "completed", "aggregated_verdict": {"verdict": "PASS"}}),
        ])
        assert result.returncode == 0
        assert outputs.get("verdict") == "PASS"

    def test_completed_fail_verdict_exits_nonzero(self):
        """FAIL verdict with fail-on-verdict=true exits 1."""
        result, outputs = _run_with_mock([
            (200, {"status": "completed", "aggregated_verdict": {"verdict": "FAIL"}}),
        ], extra_env={"CERBERUS_FAIL_ON_VERDICT": "true"})
        assert result.returncode == 1
        assert outputs.get("verdict") == "FAIL"

    def test_completed_fail_verdict_no_fail_exits_zero(self):
        """FAIL verdict with fail-on-verdict=false exits 0."""
        result, outputs = _run_with_mock([
            (200, {"status": "completed", "aggregated_verdict": {"verdict": "FAIL"}}),
        ], extra_env={"CERBERUS_FAIL_ON_VERDICT": "false"})
        assert result.returncode == 0
        assert outputs.get("verdict") == "FAIL"

    def test_completed_warn_verdict(self):
        """WARN verdict exits 0."""
        result, outputs = _run_with_mock([
            (200, {"status": "completed", "aggregated_verdict": {"verdict": "WARN"}}),
        ])
        assert result.returncode == 0
        assert outputs.get("verdict") == "WARN"

    def test_failed_status_exits_nonzero(self):
        """Server-side pipeline failure exits 1 with SKIP verdict."""
        result, outputs = _run_with_mock([
            (200, {"status": "running"}),
            (200, {"status": "failed"}),
        ])
        assert result.returncode == 1
        assert outputs.get("verdict") == "SKIP"

    def test_timeout_exits_nonzero(self):
        """Exceeding TIMEOUT exits 1 with SKIP verdict."""
        # Always return running — will hit 3s timeout
        result, outputs = _run_with_mock(
            [(200, {"status": "running"})],
            extra_env={"CERBERUS_TIMEOUT": "3", "CERBERUS_POLL_INTERVAL": "1"},
        )
        assert result.returncode == 1
        assert outputs.get("verdict") == "SKIP"

    def test_consecutive_poll_errors_abort(self):
        """Too many consecutive HTTP errors aborts with SKIP."""
        # Return 500 errors — should abort after MAX_POLL_ERRORS (10)
        result, outputs = _run_with_mock(
            [(500, {"error": "internal"})],
            extra_env={"CERBERUS_TIMEOUT": "30", "CERBERUS_POLL_INTERVAL": "1"},
        )
        assert result.returncode == 1
        assert outputs.get("verdict") == "SKIP"

    def test_transient_errors_recover(self):
        """A few HTTP errors followed by success don't abort."""
        result, outputs = _run_with_mock([
            (500, {"error": "transient"}),
            (500, {"error": "transient"}),
            (200, {"status": "completed", "aggregated_verdict": {"verdict": "PASS"}}),
        ])
        assert result.returncode == 0
        assert outputs.get("verdict") == "PASS"

    def test_timeout_boundary_exact(self):
        """TIMEOUT=2, POLL_INTERVAL=2 — exits after exactly 1 poll."""
        result, outputs = _run_with_mock(
            [(200, {"status": "running"})],
            extra_env={"CERBERUS_TIMEOUT": "2", "CERBERUS_POLL_INTERVAL": "2"},
        )
        assert result.returncode == 1
        assert outputs.get("verdict") == "SKIP"
        # review-id is set before the poll loop, so it should still be present
        assert "review-id" in outputs

    def test_unknown_status_continues_polling(self):
        """Unknown status emits a warning but keeps polling until completion."""
        result, outputs = _run_with_mock([
            (200, {"status": "initializing"}),
            (200, {"status": "completed", "aggregated_verdict": {"verdict": "PASS"}}),
        ])
        assert result.returncode == 0
        assert outputs.get("verdict") == "PASS"
        assert "Unknown status: initializing" in result.stdout

    def test_runner_temp_verdict_file(self):
        """Verdict JSON is written to RUNNER_TEMP when set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result, outputs = _run_with_mock(
                [(200, {"status": "completed", "aggregated_verdict": {"verdict": "PASS"}})],
                extra_env={"RUNNER_TEMP": tmpdir},
            )
            assert result.returncode == 0
            verdict_path = os.path.join(tmpdir, "cerberus-api-verdict.json")
            assert os.path.exists(verdict_path)
            with open(verdict_path) as f:
                data = json.load(f)
            assert data["aggregated_verdict"]["verdict"] == "PASS"
