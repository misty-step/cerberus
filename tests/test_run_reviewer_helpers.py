"""Focused unit tests for helper/error branches in scripts/run-reviewer.py."""

import importlib
from pathlib import Path

import pytest

_script_path = Path(__file__).parent.parent / "scripts" / "run-reviewer.py"
_spec = importlib.util.spec_from_file_location("run_reviewer_py", _script_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def _write_fake_root(
    tmp_path: Path,
    *,
    config_yml: str | None = None,
    agent_content: str = "System prompt body\n",
) -> Path:
    root = tmp_path / "cerberus-root"
    (root / "defaults").mkdir(parents=True)
    (root / "templates").mkdir(parents=True)
    (root / ".opencode" / "agents").mkdir(parents=True)

    if config_yml is None:
        config_yml = "- name: SENTINEL\n  perspective: security\n"

    (root / "defaults" / "config.yml").write_text(config_yml)
    (root / "templates" / "review-prompt.md").write_text("{{DIFF_FILE}}\n{{PERSPECTIVE}}\n")
    (root / ".opencode" / "agents" / "security.md").write_text(agent_content)
    return root


def _set_base_env(monkeypatch, tmp_path: Path, root: Path, *, with_diff: bool = True, with_api_key: bool = True) -> None:
    cerberus_tmp = tmp_path / "tmp"
    cerberus_tmp.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("CERBERUS_ROOT", str(root))
    monkeypatch.setenv("CERBERUS_TMP", str(cerberus_tmp))
    monkeypatch.setenv("REVIEW_TIMEOUT", "5")
    monkeypatch.setenv("OPENCODE_MAX_STEPS", "5")
    monkeypatch.setenv("CERBERUS_TEST_NO_SLEEP", "1")

    if with_diff:
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text("diff --git a/app.py b/app.py\n+print('hello')\n")
        monkeypatch.setenv("GH_DIFF_FILE", str(diff_file))
        monkeypatch.delenv("GH_DIFF", raising=False)
    else:
        monkeypatch.delenv("GH_DIFF_FILE", raising=False)
        monkeypatch.delenv("GH_DIFF", raising=False)

    if with_api_key:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    else:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("CERBERUS_OPENROUTER_API_KEY", raising=False)


def test_parse_positive_int_and_sanitize_model() -> None:
    assert _mod.parse_positive_int(None, 7) == 7
    assert _mod.parse_positive_int("not-an-int", 7) == 7
    assert _mod.parse_positive_int("9", 7) == 9
    assert _mod.sanitize_model('"openrouter/x/y"') == "openrouter/x/y"


def test_maybe_sleep_handles_zero_and_positive(monkeypatch) -> None:
    calls: list[int] = []

    def fake_sleep(seconds: int) -> None:
        calls.append(seconds)

    monkeypatch.setattr(_mod.time, "sleep", fake_sleep)
    monkeypatch.delenv("CERBERUS_TEST_NO_SLEEP", raising=False)

    _mod.maybe_sleep(0)
    _mod.maybe_sleep(2)

    assert calls == [2]


def test_extract_diff_files_skips_malformed_and_caps_at_20(tmp_path: Path) -> None:
    diff_file = tmp_path / "large.diff"
    lines = ["diff --git malformed\n"]
    for i in range(25):
        lines.append(
            f"diff --git a/src/f{i}.py b/src/f{i}.py\n"
            "index 1111111..2222222 100644\n"
            f"--- a/src/f{i}.py\n"
            f"+++ b/src/f{i}.py\n"
        )
    diff_file.write_text("".join(lines))

    files = _mod.extract_diff_files(diff_file)
    assert len(files) == 20
    assert files[0] == "src/f0.py"
    assert files[-1] == "src/f19.py"


def test_strip_frontmatter_without_closing_marker_returns_original() -> None:
    text = "---\nname: test\nno-closing-marker"
    assert _mod.strip_frontmatter(text) == text


def test_resolve_profile_wraps_profile_errors(tmp_path: Path) -> None:
    root = _write_fake_root(tmp_path)
    (root / "defaults" / "reviewer-profiles.yml").write_text("version: [\n")

    with pytest.raises(RuntimeError, match="reviewer profiles error"):
        _mod.resolve_profile(root, "security")


def test_classify_api_error_text_branches() -> None:
    assert _mod.classify_api_error_text("insufficient_quota") == "API_CREDITS_DEPLETED"
    assert _mod.classify_api_error_text("random error") == "API_ERROR"


def test_print_tail_missing_file(capsys, tmp_path: Path) -> None:
    _mod.print_tail(tmp_path / "missing.txt")
    captured = capsys.readouterr().out
    assert "(missing parse input file)" in captured


def test_main_requires_perspective_argument(capsys) -> None:
    code = _mod.main([])
    assert code == 2
    assert "usage: run-reviewer.sh <perspective>" in capsys.readouterr().err


def test_main_requires_cerberus_root(monkeypatch, capsys) -> None:
    monkeypatch.delenv("CERBERUS_ROOT", raising=False)
    code = _mod.main(["security"])
    assert code == 2
    assert "CERBERUS_ROOT not set" in capsys.readouterr().err


def test_main_defaults_config_error(monkeypatch, tmp_path: Path, capsys) -> None:
    root = _write_fake_root(tmp_path, config_yml="invalid: [\n")
    _set_base_env(monkeypatch, tmp_path, root)

    code = _mod.main(["security"])
    assert code == 2
    assert "defaults config error" in capsys.readouterr().err


def test_main_unknown_perspective_in_config(monkeypatch, tmp_path: Path, capsys) -> None:
    root = _write_fake_root(
        tmp_path,
        config_yml="- name: ATLAS\n  perspective: architecture\n",
    )
    _set_base_env(monkeypatch, tmp_path, root)

    code = _mod.main(["security"])
    assert code == 2
    assert "unknown perspective in config" in capsys.readouterr().err


def test_main_profile_resolution_error(monkeypatch, tmp_path: Path, capsys) -> None:
    root = _write_fake_root(tmp_path)
    (root / "defaults" / "reviewer-profiles.yml").write_text("version: [\n")
    _set_base_env(monkeypatch, tmp_path, root)

    code = _mod.main(["security"])
    assert code == 2
    assert "reviewer profiles error" in capsys.readouterr().err


def test_main_missing_api_key(monkeypatch, tmp_path: Path, capsys) -> None:
    root = _write_fake_root(tmp_path)
    _set_base_env(monkeypatch, tmp_path, root, with_api_key=False)

    code = _mod.main(["security"])
    assert code == 2
    assert "missing OPENROUTER_API_KEY" in capsys.readouterr().err


def test_main_missing_diff_input(monkeypatch, tmp_path: Path, capsys) -> None:
    root = _write_fake_root(tmp_path)
    _set_base_env(monkeypatch, tmp_path, root, with_diff=False)

    code = _mod.main(["security"])
    assert code == 2
    assert "missing diff input" in capsys.readouterr().err


def test_main_render_prompt_error(monkeypatch, tmp_path: Path, capsys) -> None:
    root = _write_fake_root(tmp_path)
    _set_base_env(monkeypatch, tmp_path, root)

    def _boom(**kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(_mod, "render_review_prompt_file", _boom)

    code = _mod.main(["security"])
    assert code == 2
    assert "render-review-prompt" in capsys.readouterr().err


def test_main_invalid_agent_prompt_body(monkeypatch, tmp_path: Path, capsys) -> None:
    root = _write_fake_root(
        tmp_path,
        agent_content="---\ndescription: test\n---\n",
    )
    _set_base_env(monkeypatch, tmp_path, root)

    code = _mod.main(["security"])
    assert code == 2
    assert "invalid agent prompt body" in capsys.readouterr().err
