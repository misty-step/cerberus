"""Tests for the Cerberus LLM router (router/route.py)."""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "router"))

import route  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG_YML = textwrap.dedent("""\
    model:
      default: "openrouter/moonshotai/kimi-k2.5"
      pool:
        - "openrouter/model-a"
        - "openrouter/model-b"

    routing:
      enabled: true
      model: "openrouter/google/gemini-3-flash-preview"
      panel_size: 5
      always_include:
        - trace
      include_if_code_changed:
        - guard
      fallback_panel:
        - trace
        - atlas
        - guard
        - craft
        - proof

    reviewers:
      - name: trace
        perspective: correctness
        model: "openrouter/moonshotai/kimi-k2.5"
        description: "Correctness — Find the bug"
      - name: atlas
        perspective: architecture
        model: "openrouter/z-ai/glm-5"
        description: "Architecture — Zoom out"
      - name: guard
        perspective: security
        model: "openrouter/minimax/minimax-m2.5"
        description: "Security — Think like an attacker"
      - name: flux
        perspective: performance
        model: "openrouter/google/gemini-3-flash-preview"
        description: "Performance — Think at runtime"
      - name: craft
        perspective: maintainability
        model: "openrouter/moonshotai/kimi-k2.5"
        description: "Maintainability — Think like the next dev"
      - name: proof
        perspective: testing
        model: "openrouter/google/gemini-3-flash-preview"
        description: "Testing — See what will break"
      - name: fuse
        perspective: resilience
        model: pool
        description: "Resilience — What happens when the happy path fails"
      - name: pact
        perspective: compatibility
        model: pool
        description: "Compatibility — Trace the client impact"
""")

SAMPLE_DIFF = textwrap.dedent("""\
    diff --git a/src/auth.py b/src/auth.py
    --- a/src/auth.py
    +++ b/src/auth.py
    @@ -10,6 +10,8 @@
     def authenticate(user, password):
    +    if not user:
    +        raise ValueError("user required")
         return check_password(user, password)
    diff --git a/tests/test_auth.py b/tests/test_auth.py
    --- a/tests/test_auth.py
    +++ b/tests/test_auth.py
    @@ -1,3 +1,5 @@
    +def test_empty_user():
    +    assert True
     def test_login():
         assert True
    diff --git a/README.md b/README.md
    --- a/README.md
    +++ b/README.md
    @@ -1 +1,2 @@
     # Auth
    +New docs
""")


@pytest.fixture()
def cerberus_root(tmp_path: Path) -> Path:
    root = tmp_path / "cerberus"
    (root / "defaults").mkdir(parents=True)
    (root / "defaults" / "config.yml").write_text(SAMPLE_CONFIG_YML)
    return root


@pytest.fixture()
def diff_file(tmp_path: Path) -> Path:
    p = tmp_path / "test.diff"
    p.write_text(SAMPLE_DIFF)
    return p


@pytest.fixture()
def cfg(cerberus_root: Path) -> dict[str, Any]:
    return route.load_config(str(cerberus_root))


@pytest.fixture(autouse=True)
def cleanup_router_output() -> None:
    yield
    Path(route.OUTPUT_PATH).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_as_int_valid(self) -> None:
        assert route.as_int("5", 3) == 5
        assert route.as_int(10, 3) == 10

    def test_as_int_invalid(self) -> None:
        assert route.as_int("abc", 7) == 7
        assert route.as_int(None, 7) == 7
        assert route.as_int(-1, 7) == 7
        assert route.as_int(0, 7) == 7

    def test_clean_token(self) -> None:
        assert route.clean_token("  TRACE  ") == "trace"
        assert route.clean_token('"guard"') == "guard"
        assert route.clean_token("'craft'") == "craft"

    def test_unique_ordered(self) -> None:
        assert route.unique_ordered(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
        assert route.unique_ordered([]) == []
        assert route.unique_ordered(["", "a", ""]) == ["a"]

    def test_split_description_em_dash(self) -> None:
        role, focus = route.split_description("Correctness — Find the bug")
        assert role == "Correctness"
        assert focus == "Find the bug"

    def test_split_description_hyphen(self) -> None:
        role, focus = route.split_description("Correctness - Find the bug")
        assert role == "Correctness"
        assert focus == "Find the bug"

    def test_split_description_plain(self) -> None:
        role, focus = route.split_description("Just a description")
        assert role == "Just a description"
        assert focus == ""

    def test_split_description_empty(self) -> None:
        assert route.split_description("") == ("", "")
        assert route.split_description(None) == ("", "")


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

class TestFileClassification:
    def test_doc_files(self) -> None:
        assert route.is_doc_path("README.md")
        assert route.is_doc_path("docs/guide.rst")
        assert route.is_doc_path("CHANGELOG.md")
        assert route.is_doc_path("doc/api.txt")

    def test_test_files(self) -> None:
        assert route.is_test_path("tests/test_foo.py")
        assert route.is_test_path("src/test/java/Foo.java")
        assert route.is_test_path("widget.test.ts")
        assert route.is_test_path("widget.spec.js")

    def test_code_files(self) -> None:
        doc, test, code = route.classify_file("src/app.py")
        assert code and not doc and not test

    def test_doc_not_code(self) -> None:
        doc, test, code = route.classify_file("docs/guide.md")
        assert doc and not code

    def test_test_not_code(self) -> None:
        doc, test, code = route.classify_file("tests/test_foo.py")
        assert test and not code


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_loads_8_reviewers(self, cfg: dict[str, Any]) -> None:
        assert len(cfg["bench"]) == 8
        assert len(cfg["perspectives"]) == 8

    def test_perspectives_ordered(self, cfg: dict[str, Any]) -> None:
        assert cfg["perspectives"][0] == "correctness"
        assert cfg["perspectives"][-1] == "compatibility"

    def test_name_to_perspective(self, cfg: dict[str, Any]) -> None:
        assert cfg["name_to_perspective"]["trace"] == "correctness"
        assert cfg["name_to_perspective"]["guard"] == "security"
        assert cfg["name_to_perspective"]["pact"] == "compatibility"

    def test_always_include(self, cfg: dict[str, Any]) -> None:
        assert cfg["always_names"] == ["trace"]

    def test_guard_names(self, cfg: dict[str, Any]) -> None:
        assert cfg["guard_names"] == ["guard"]

    def test_fallback_names(self, cfg: dict[str, Any]) -> None:
        assert cfg["fallback_names"] == ["trace", "atlas", "guard", "craft", "proof"]

    def test_default_panel_size(self, cfg: dict[str, Any]) -> None:
        assert cfg["default_panel_size"] == 5


class TestModelTierClassification:
    def test_flash_tier(self) -> None:
        assert route.classify_model_tier(
            {
                "total_changed_lines": 10,
                "code_files": 0,
                "test_files": 1,
                "doc_files": 0,
                "files": [{"path": "tests/test_foo.py"}],
            }
        ) == route.MODEL_TIER_FLASH

    def test_pro_tier_from_size(self) -> None:
        assert route.classify_model_tier(
            {
                "total_changed_lines": 500,
                "code_files": 4,
                "test_files": 1,
                "doc_files": 0,
                "files": [{"path": "src/app.py"}],
            }
        ) == route.MODEL_TIER_PRO

    def test_pro_tier_from_security_hint(self) -> None:
        assert route.classify_model_tier(
            {
                "total_changed_lines": 10,
                "code_files": 1,
                "test_files": 0,
                "doc_files": 0,
                "files": [{"path": "api/auth.py"}],
            }
        ) == route.MODEL_TIER_PRO

    def test_standard_tier(self) -> None:
        assert route.classify_model_tier(
            {
                "total_changed_lines": 120,
                "code_files": 2,
                "test_files": 1,
                "doc_files": 0,
                "files": [{"path": "src/app.py"}],
            }
        ) == route.MODEL_TIER_STANDARD


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------

class TestParseDiff:
    def test_parses_files(self, diff_file: Path) -> None:
        summary = route.parse_diff(str(diff_file))
        assert summary["total_files"] == 3
        assert summary["code_files"] == 1
        assert summary["test_files"] == 1
        assert summary["doc_files"] == 1
        assert summary["code_changed"] is True

    def test_counts_additions_deletions(self, diff_file: Path) -> None:
        summary = route.parse_diff(str(diff_file))
        assert summary["total_additions"] == 5
        assert summary["total_deletions"] == 0

    def test_missing_diff_returns_empty(self) -> None:
        summary = route.parse_diff("/nonexistent/file.diff")
        assert summary["total_files"] == 0
        assert summary["code_changed"] is False

    def test_doc_only_diff(self, tmp_path: Path) -> None:
        doc_diff = tmp_path / "doc.diff"
        doc_diff.write_text(
            "diff --git a/README.md b/README.md\n"
            "+new line\n"
        )
        summary = route.parse_diff(str(doc_diff))
        assert summary["doc_files"] == 1
        assert summary["code_files"] == 0
        assert summary["code_changed"] is False

    def test_extensions_histogram(self, diff_file: Path) -> None:
        summary = route.parse_diff(str(diff_file))
        assert ".py" in summary["extensions"]
        assert ".md" in summary["extensions"]


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------

class TestResolveTokens:
    def test_resolve_by_name(self, cfg: dict[str, Any]) -> None:
        result = route.resolve_tokens(["trace", "guard"], cfg)
        assert result == ["correctness", "security"]

    def test_resolve_by_perspective(self, cfg: dict[str, Any]) -> None:
        result = route.resolve_tokens(["correctness", "security"], cfg)
        assert result == ["correctness", "security"]

    def test_mixed_name_and_perspective(self, cfg: dict[str, Any]) -> None:
        result = route.resolve_tokens(["trace", "security"], cfg)
        assert result == ["correctness", "security"]

    def test_invalid_token_ignored(self, cfg: dict[str, Any]) -> None:
        result = route.resolve_tokens(["trace", "bogus", "guard"], cfg)
        assert result == ["correctness", "security"]

    def test_deduplication(self, cfg: dict[str, Any]) -> None:
        result = route.resolve_tokens(["trace", "correctness", "trace"], cfg)
        assert result == ["correctness"]


# ---------------------------------------------------------------------------
# Required perspectives
# ---------------------------------------------------------------------------

class TestRequiredPerspectives:
    def test_code_changed_includes_guard(self, cfg: dict[str, Any]) -> None:
        required = route.required_perspectives(cfg, code_changed=True)
        assert "correctness" in required
        assert "security" in required

    def test_no_code_excludes_guard(self, cfg: dict[str, Any]) -> None:
        required = route.required_perspectives(cfg, code_changed=False)
        assert "correctness" in required
        assert "security" not in required


# ---------------------------------------------------------------------------
# Fallback panel
# ---------------------------------------------------------------------------

class TestBuildFallbackPanel:
    def test_fallback_panel_size(self, cfg: dict[str, Any]) -> None:
        panel = route.build_fallback_panel(cfg, 5, code_changed=True)
        assert len(panel) == 5

    def test_fallback_includes_required(self, cfg: dict[str, Any]) -> None:
        panel = route.build_fallback_panel(cfg, 5, code_changed=True)
        assert "correctness" in panel
        assert "security" in panel

    def test_fallback_respects_config(self, cfg: dict[str, Any]) -> None:
        panel = route.build_fallback_panel(cfg, 5, code_changed=True)
        assert panel == ["correctness", "security", "architecture", "maintainability", "testing"]

    def test_fallback_smaller_size(self, cfg: dict[str, Any]) -> None:
        panel = route.build_fallback_panel(cfg, 3, code_changed=True)
        assert len(panel) == 3
        assert "correctness" in panel
        assert "security" in panel


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_prompt_contains_bench(self, cfg: dict[str, Any]) -> None:
        summary = {"code_changed": True, "total_files": 3, "total_additions": 10,
                    "total_deletions": 2, "total_changed_lines": 12, "code_files": 2,
                    "test_files": 1, "doc_files": 0, "extensions": {".py": 2, ".ts": 1},
                    "files": []}
        prompt = route.build_prompt(cfg, summary, 5)
        assert "trace" in prompt
        assert "guard" in prompt
        assert "fuse" in prompt
        assert "Select EXACTLY 5" in prompt

    def test_prompt_lists_required(self, cfg: dict[str, Any]) -> None:
        summary = {"code_changed": True, "total_files": 1, "total_additions": 1,
                    "total_deletions": 0, "total_changed_lines": 1, "code_files": 1,
                    "test_files": 0, "doc_files": 0, "extensions": {".py": 1},
                    "files": []}
        prompt = route.build_prompt(cfg, summary, 5)
        assert "correctness, security" in prompt

    def test_prompt_no_code_skips_guard(self, cfg: dict[str, Any]) -> None:
        summary = {"code_changed": False, "total_files": 1, "total_additions": 1,
                    "total_deletions": 0, "total_changed_lines": 1, "code_files": 0,
                    "test_files": 0, "doc_files": 1, "extensions": {".md": 1},
                    "files": []}
        prompt = route.build_prompt(cfg, summary, 5)
        # Required should only be correctness, not security
        assert "Required perspectives for this PR: correctness\n" in prompt


# ---------------------------------------------------------------------------
# Panel parsing from model output
# ---------------------------------------------------------------------------

class TestParsePanelFromText:
    def test_valid_json_array(self) -> None:
        raw = '["correctness","security","architecture","testing","maintainability"]'
        assert route.parse_panel_from_text(raw) == [
            "correctness", "security", "architecture", "testing", "maintainability"
        ]

    def test_fenced_json(self) -> None:
        raw = '```json\n["correctness","security","architecture"]\n```'
        assert route.parse_panel_from_text(raw) == ["correctness", "security", "architecture"]

    def test_json_with_surrounding_text(self) -> None:
        raw = 'Here is my selection:\n["correctness","security","testing"]\nDone.'
        result = route.parse_panel_from_text(raw)
        assert result == ["correctness", "security", "testing"]

    def test_dict_with_panel_key(self) -> None:
        raw = '{"panel": ["correctness", "security"]}'
        assert route.parse_panel_from_text(raw) == ["correctness", "security"]

    def test_empty_input(self) -> None:
        assert route.parse_panel_from_text(None) == []
        assert route.parse_panel_from_text("") == []

    def test_invalid_json(self) -> None:
        assert route.parse_panel_from_text("not json at all") == []


# ---------------------------------------------------------------------------
# Panel validation
# ---------------------------------------------------------------------------

class TestValidatePanel:
    def test_valid_panel(self, cfg: dict[str, Any]) -> None:
        panel = ["correctness", "security", "architecture", "testing", "maintainability"]
        result = route.validate_panel(panel, cfg, 5, code_changed=True)
        assert result == panel

    def test_wrong_size_rejected(self, cfg: dict[str, Any]) -> None:
        panel = ["correctness", "security", "architecture"]
        assert route.validate_panel(panel, cfg, 5, code_changed=True) == []

    def test_missing_required_rejected(self, cfg: dict[str, Any]) -> None:
        # Missing correctness (always required)
        panel = ["security", "architecture", "testing", "maintainability", "performance"]
        assert route.validate_panel(panel, cfg, 5, code_changed=True) == []

    def test_missing_guard_when_code_changed(self, cfg: dict[str, Any]) -> None:
        # Missing security when code changed
        panel = ["correctness", "architecture", "testing", "maintainability", "performance"]
        assert route.validate_panel(panel, cfg, 5, code_changed=True) == []

    def test_guard_not_required_for_doc_only(self, cfg: dict[str, Any]) -> None:
        panel = ["correctness", "architecture", "resilience", "testing", "maintainability"]
        result = route.validate_panel(panel, cfg, 5, code_changed=False)
        assert result == panel

    def test_invalid_perspective_rejected(self, cfg: dict[str, Any]) -> None:
        panel = ["correctness", "security", "architecture", "testing", "bogus"]
        assert route.validate_panel(panel, cfg, 5, code_changed=True) == []

    def test_names_resolved_to_perspectives(self, cfg: dict[str, Any]) -> None:
        # Using codenames instead of perspectives
        panel = ["trace", "guard", "atlas", "craft", "proof"]
        result = route.validate_panel(panel, cfg, 5, code_changed=True)
        assert result == ["correctness", "security", "architecture", "maintainability", "testing"]


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

class TestWriteOutput:
    def test_writes_json(self) -> None:
        route.write_output(
            ["correctness", "security"],
            True,
            "test-model",
            route.MODEL_TIER_STANDARD,
        )
        data = json.loads(Path(route.OUTPUT_PATH).read_text())
        assert data["panel"] == ["correctness", "security"]
        assert data["routing_used"] is True
        assert data["model"] == "test-model"
        assert data["model_tier"] == route.MODEL_TIER_STANDARD


# ---------------------------------------------------------------------------
# Main integration (env-driven, mocked API)
# ---------------------------------------------------------------------------

class TestMainIntegration:
    def _run_main(self, env: dict[str, str]) -> dict[str, Any]:
        """Run main() with mocked environment and return output."""
        with mock.patch.dict(os.environ, env, clear=False):
            route.main()
        return json.loads(Path(route.OUTPUT_PATH).read_text())

    def test_forced_reviewers(self, cerberus_root: Path, diff_file: Path) -> None:
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "trace,guard,atlas",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert result["panel"] == ["correctness", "security", "architecture"]
        assert result["routing_used"] is False
        assert result["model"] == "forced"
        assert result["model_tier"] == route.MODEL_TIER_STANDARD

    def test_routing_disabled(self, cerberus_root: Path, diff_file: Path) -> None:
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "disabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        # Should return all 8 perspectives
        assert len(result["panel"]) == 8
        assert result["routing_used"] is False
        assert result["model"] == "disabled"
        assert result["model_tier"] == route.MODEL_TIER_STANDARD

    def test_missing_api_key_uses_fallback(self, cerberus_root: Path, diff_file: Path) -> None:
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "",
            "CERBERUS_OPENROUTER_API_KEY": "",
        })
        assert len(result["panel"]) == 5
        assert result["routing_used"] is False
        assert result["model_tier"] == route.MODEL_TIER_STANDARD

    @mock.patch("route.call_router")
    def test_prefers_cerberus_openrouter_key_over_legacy_openrouter_key(
        self,
        mock_call: mock.Mock,
        cerberus_root: Path,
        diff_file: Path,
    ) -> None:
        mock_call.return_value = (
            '["correctness","security","architecture","resilience","compatibility"]',
            "google/gemini-3-flash-preview",
        )
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "CERBERUS_OPENROUTER_API_KEY": "new-key",
            "OPENROUTER_API_KEY": "legacy-key",
        })
        assert result["routing_used"] is True
        assert mock_call.call_args is not None
        assert mock_call.call_args.args[0] == "new-key"

    @mock.patch("route.call_router")
    def test_uses_cerberus_openrouter_key_when_legacy_openrouter_missing(
        self,
        mock_call: mock.Mock,
        cerberus_root: Path,
        diff_file: Path,
    ) -> None:
        mock_call.return_value = (
            '["correctness","security","architecture","resilience","compatibility"]',
            "google/gemini-3-flash-preview",
        )
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "CERBERUS_OPENROUTER_API_KEY": "new-key",
            "OPENROUTER_API_KEY": "",
        })
        assert result["routing_used"] is True
        assert mock_call.call_args is not None
        assert mock_call.call_args.args[0] == "new-key"

    @mock.patch("route.call_router")
    def test_successful_routing(self, mock_call: mock.Mock,
                                 cerberus_root: Path, diff_file: Path) -> None:
        mock_call.return_value = (
            '["correctness","security","architecture","resilience","compatibility"]',
            "google/gemini-3-flash-preview",
        )
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert result["panel"] == [
            "correctness", "security", "architecture", "resilience", "compatibility"
        ]
        assert result["routing_used"] is True
        assert result["model_tier"] == route.MODEL_TIER_PRO

    @mock.patch("route.call_router")
    def test_invalid_router_output_falls_back(self, mock_call: mock.Mock,
                                               cerberus_root: Path, diff_file: Path) -> None:
        # Return garbage
        mock_call.return_value = ("this is not json", "some-model")
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert len(result["panel"]) == 5
        assert result["routing_used"] is False
        assert result["model_tier"] == route.MODEL_TIER_PRO

    @mock.patch("route.call_router")
    def test_wrong_panel_size_falls_back(self, mock_call: mock.Mock,
                                          cerberus_root: Path, diff_file: Path) -> None:
        # Return only 3 instead of 5
        mock_call.return_value = (
            '["correctness","security","architecture"]',
            "some-model",
        )
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert len(result["panel"]) == 5
        assert result["routing_used"] is False
        assert result["model_tier"] == route.MODEL_TIER_PRO

    @mock.patch("route.call_router")
    def test_missing_required_reviewer_falls_back(self, mock_call: mock.Mock,
                                                    cerberus_root: Path, diff_file: Path) -> None:
        # Missing correctness (always required via trace)
        mock_call.return_value = (
            '["security","architecture","testing","compatibility","resilience"]',
            "some-model",
        )
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert result["routing_used"] is False
        assert "correctness" in result["panel"]
        assert result["model_tier"] == route.MODEL_TIER_PRO

    @mock.patch("route.call_router")
    def test_api_returns_none(self, mock_call: mock.Mock,
                               cerberus_root: Path, diff_file: Path) -> None:
        mock_call.return_value = (None, "some-model")
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert result["routing_used"] is False
        assert len(result["panel"]) == 5
        assert result["model_tier"] == route.MODEL_TIER_PRO

    def test_invalid_forced_reviewers_uses_fallback(self, cerberus_root: Path, diff_file: Path) -> None:
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "bogus,nope,fake",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert result["routing_used"] is False
        assert len(result["panel"]) == 5
        assert result["model_tier"] == route.MODEL_TIER_STANDARD

    def test_custom_panel_size(self, cerberus_root: Path, diff_file: Path) -> None:
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "disabled",
            "PANEL_SIZE": "3",
            "OPENROUTER_API_KEY": "fake-key",
        })
        # Disabled routing returns full bench, not panel_size-limited
        assert len(result["panel"]) == 8
        assert result["model_tier"] == route.MODEL_TIER_STANDARD

    def test_config_load_failure_uses_hardcoded_fallback(self, tmp_path: Path, diff_file: Path) -> None:
        result = self._run_main({
            "CERBERUS_ROOT": str(tmp_path / "nonexistent"),
            "DIFF_FILE": str(diff_file),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert result["panel"] == route.DEFAULT_PANEL[:5]
        assert result["routing_used"] is False
        assert result["model_tier"] == route.MODEL_TIER_STANDARD

    @mock.patch("route.call_router")
    def test_successful_routing_uses_flash_tier(self, mock_call: mock.Mock,
                                                cerberus_root: Path, tmp_path: Path) -> None:
        mock_call.return_value = (
            '["correctness","security","architecture","resilience","compatibility"]',
            "google/gemini-3-flash-preview",
        )
        doc_diff = tmp_path / "doc.diff"
        doc_diff.write_text("diff --git a/tests/test_auth.py b/tests/test_auth.py\n+def test_auth():\n    assert True\n")
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(doc_diff),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert result["model_tier"] == route.MODEL_TIER_FLASH

    @mock.patch("route.call_router")
    def test_successful_routing_uses_pro_tier_for_security_hint(self, mock_call: mock.Mock,
                                                               cerberus_root: Path, tmp_path: Path) -> None:
        mock_call.return_value = (
            '["correctness","security","architecture","resilience","compatibility"]',
            "google/gemini-3-flash-preview",
        )
        security_diff = tmp_path / "security.diff"
        security_diff.write_text(
            "diff --git a/api/oauth.py b/api/oauth.py\n+print('oauth')\n"
        )
        result = self._run_main({
            "CERBERUS_ROOT": str(cerberus_root),
            "DIFF_FILE": str(security_diff),
            "FORCED_REVIEWERS": "",
            "ROUTING": "enabled",
            "OPENROUTER_API_KEY": "fake-key",
        })
        assert result["model_tier"] == route.MODEL_TIER_PRO
