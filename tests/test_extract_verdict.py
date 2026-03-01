"""Tests for scripts/extract-verdict.py."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "extract-verdict.py"

spec = importlib.util.spec_from_file_location("extract_verdict_script", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def _minimal_verdict() -> dict:
    return {
        "verdict": "PASS",
        "confidence": 0.9,
        "summary": "All good.",
        "findings": [],
        "stats": {
            "files_reviewed": 3,
            "files_with_issues": 0,
            "critical": 0,
            "major": 0,
            "minor": 0,
            "info": 0,
        },
    }


def _mock_response(verdict: dict, usage: dict | None = None) -> MagicMock:
    """Build a mock urllib response wrapping a verdict JSON."""
    body_dict: dict = {"choices": [{"message": {"content": json.dumps(verdict)}}]}
    if usage is not None:
        body_dict["usage"] = usage
    body = json.dumps(body_dict).encode("utf-8")
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read = MagicMock(return_value=body)
    return mock


class TestMain:
    def test_missing_args_returns_2(self, capsys: pytest.CaptureFixture) -> None:
        code = mod.main([])
        assert code == 2

    def test_only_one_arg_returns_2(self, capsys: pytest.CaptureFixture) -> None:
        code = mod.main(["somefile"])
        assert code == 2

    def test_missing_api_key_returns_1(self, tmp_path: Path) -> None:
        f = tmp_path / "scratch.md"
        f.write_text("## Notes\nLooks fine.")

        env = {k: v for k, v in os.environ.items()
               if k not in {"CERBERUS_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"}}
        with patch.dict(os.environ, env, clear=True):
            code = mod.main([str(f), "correctness"])
        assert code == 1

    def test_missing_file_returns_1(self, tmp_path: Path) -> None:
        env = {**os.environ, "CERBERUS_OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env):
            code = mod.main([str(tmp_path / "nonexistent.md"), "correctness"])
        assert code == 1

    def test_empty_file_returns_1(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("")
        env = {**os.environ, "CERBERUS_OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env):
            code = mod.main([str(f), "correctness"])
        assert code == 1

    def test_happy_path_writes_verdict(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        f = tmp_path / "scratch.md"
        f.write_text("## Review Notes\nThe code is correct.")
        verdict = _minimal_verdict()

        env = {**os.environ, "CERBERUS_OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env):
            with patch("urllib.request.urlopen", return_value=_mock_response(verdict)):
                code = mod.main([str(f), "correctness"])

        assert code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["verdict"] == "PASS"
        assert parsed["confidence"] == 0.9

    def test_usage_included_in_output_when_present(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        f = tmp_path / "scratch.md"
        f.write_text("## Review Notes\nThe code is correct.")
        verdict = _minimal_verdict()
        usage = {"prompt_tokens": 100, "completion_tokens": 50}

        env = {**os.environ, "CERBERUS_OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env):
            with patch("urllib.request.urlopen", return_value=_mock_response(verdict, usage=usage)):
                code = mod.main([str(f), "correctness"])

        assert code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "_extraction_usage" in parsed
        assert parsed["_extraction_usage"]["prompt_tokens"] == 100
        assert parsed["_extraction_usage"]["completion_tokens"] == 50

    def test_usage_not_included_when_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        f = tmp_path / "scratch.md"
        f.write_text("## Review Notes\nThe code is correct.")
        verdict = _minimal_verdict()

        env = {**os.environ, "CERBERUS_OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env):
            # No usage in response (default _mock_response behavior)
            with patch("urllib.request.urlopen", return_value=_mock_response(verdict)):
                code = mod.main([str(f), "correctness"])

        assert code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "_extraction_usage" not in parsed

    def test_http_error_returns_1(self, tmp_path: Path) -> None:
        f = tmp_path / "scratch.md"
        f.write_text("## Notes\nSome notes.")

        http_err = urllib.error.HTTPError(
            url="https://openrouter.ai",
            code=429,
            msg="Too Many Requests",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b"rate limited"),
        )

        env = {**os.environ, "CERBERUS_OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env):
            with patch("urllib.request.urlopen", side_effect=http_err):
                code = mod.main([str(f), "correctness"])

        assert code == 1

    def test_network_error_returns_1(self, tmp_path: Path) -> None:
        f = tmp_path / "scratch.md"
        f.write_text("## Notes\nSome notes.")

        env = {**os.environ, "CERBERUS_OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env):
            with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
                code = mod.main([str(f), "correctness"])

        assert code == 1

    def test_unsupported_model_rerouted_to_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Models in _UNSUPPORTED_MODELS are silently rerouted to EXTRACTION_MODEL."""
        f = tmp_path / "scratch.md"
        f.write_text("## Notes\nLooks fine.")
        verdict = _minimal_verdict()

        captured_models: list[str] = []

        def fake_urlopen(req, timeout=None):
            payload = json.loads(req.data.decode())
            captured_models.append(payload["model"])
            return _mock_response(verdict)

        env = {**os.environ, "CERBERUS_OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                code = mod.main([str(f), "correctness", "openrouter/x-ai/grok-code-fast-1"])

        assert code == 0
        # Should have been rerouted — grok-code-fast-1 is in _UNSUPPORTED_MODELS
        assert captured_models, "no API call was made"
        assert "grok-code-fast-1" not in captured_models[0]

    def test_api_key_from_legacy_env_var(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """OPENROUTER_API_KEY is accepted as fallback when CERBERUS_ var is absent."""
        f = tmp_path / "scratch.md"
        f.write_text("## Notes\nLooks fine.")
        verdict = _minimal_verdict()

        env = {
            k: v for k, v in os.environ.items()
            if k != "CERBERUS_OPENROUTER_API_KEY"
        }
        env["OPENROUTER_API_KEY"] = "legacy-key"

        with patch.dict(os.environ, env, clear=True):
            with patch("urllib.request.urlopen", return_value=_mock_response(verdict)):
                code = mod.main([str(f), "correctness"])

        assert code == 0


class TestExtractVerdictFunction:
    def test_extracts_from_response(self) -> None:
        verdict = _minimal_verdict()

        with patch("urllib.request.urlopen", return_value=_mock_response(verdict)):
            result, usage = mod.extract_verdict(
                "## Review\nAll good.", "correctness", "kimi-k2.5", "test-key"
            )

        assert result["verdict"] == "PASS"
        assert result["stats"]["files_reviewed"] == 3

    def test_returns_usage_when_present(self) -> None:
        verdict = _minimal_verdict()
        usage = {"prompt_tokens": 200, "completion_tokens": 80}

        with patch("urllib.request.urlopen", return_value=_mock_response(verdict, usage=usage)):
            result, returned_usage = mod.extract_verdict(
                "## Review\nAll good.", "correctness", "kimi-k2.5", "test-key"
            )

        assert returned_usage == {"prompt_tokens": 200, "completion_tokens": 80}

    def test_returns_empty_usage_when_absent(self) -> None:
        verdict = _minimal_verdict()

        with patch("urllib.request.urlopen", return_value=_mock_response(verdict)):
            result, returned_usage = mod.extract_verdict(
                "## Review\nAll good.", "correctness", "kimi-k2.5", "test-key"
            )

        assert returned_usage == {}

    def test_http_error_raises(self) -> None:
        http_err = urllib.error.HTTPError(
            url="https://openrouter.ai",
            code=401,
            msg="Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b"invalid key"),
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(RuntimeError, match="HTTP 401"):
                mod.extract_verdict("notes", "correctness", "kimi-k2.5", "bad-key")

    def test_strips_openrouter_prefix_from_model(self) -> None:
        verdict = _minimal_verdict()
        captured: list[str] = []

        def fake_urlopen(req, timeout=None):
            payload = json.loads(req.data.decode())
            captured.append(payload["model"])
            return _mock_response(verdict)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            mod.extract_verdict(
                "notes", "correctness", "openrouter/moonshotai/kimi-k2.5", "key"
            )

        assert captured[0] == "moonshotai/kimi-k2.5"

    def test_malformed_response_raises(self) -> None:
        bad_resp = MagicMock()
        bad_resp.__enter__ = lambda s: s
        bad_resp.__exit__ = MagicMock(return_value=False)
        bad_resp.read = MagicMock(return_value=b'{"no_choices": true}')

        with patch("urllib.request.urlopen", return_value=bad_resp):
            with pytest.raises(RuntimeError, match="unexpected response shape"):
                mod.extract_verdict("notes", "correctness", "kimi-k2.5", "key")


class TestVerdictSchema:
    def test_schema_has_required_fields(self) -> None:
        assert "verdict" in mod.VERDICT_SCHEMA["required"]
        assert "confidence" in mod.VERDICT_SCHEMA["required"]
        assert "findings" in mod.VERDICT_SCHEMA["required"]
        assert "stats" in mod.VERDICT_SCHEMA["required"]

    def test_verdict_enum_values(self) -> None:
        enum = mod.VERDICT_SCHEMA["properties"]["verdict"]["enum"]
        assert set(enum) == {"PASS", "WARN", "FAIL", "SKIP"}

    def test_finding_required_fields(self) -> None:
        required = mod.VERDICT_SCHEMA["properties"]["findings"]["items"]["required"]
        for field in ("severity", "category", "file", "line", "title", "description", "suggestion"):
            assert field in required

    def test_stats_required_fields(self) -> None:
        required = mod.VERDICT_SCHEMA["properties"]["stats"]["required"]
        for field in ("files_reviewed", "files_with_issues", "critical", "major", "minor", "info"):
            assert field in required
