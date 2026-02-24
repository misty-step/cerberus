"""Tests for scripts/read-defaults-config.py CLI."""

import importlib
import sys
from pathlib import Path

# Import the script module directly.
_script_path = Path(__file__).parent.parent / "scripts" / "read-defaults-config.py"
_spec = importlib.util.spec_from_file_location("read_defaults_config_cli", _script_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
main = _mod.main
_single_line = _mod._single_line


class TestSingleLine:
    def test_none_returns_empty(self):
        assert _single_line(None) == ""

    def test_empty_returns_empty(self):
        assert _single_line("") == ""

    def test_multiline_collapsed(self):
        assert _single_line("hello\nworld") == "hello world"

    def test_tabs_replaced(self):
        assert _single_line("a\tb") == "a b"


def _write_config(tmp_path: Path, content: str) -> str:
    p = tmp_path / "config.yml"
    p.write_text(content)
    return str(p)


class TestReviewerMeta:
    def test_found(self, tmp_path):
        cfg = _write_config(tmp_path, """
reviewers:
  - name: APOLLO
    perspective: correctness
    model: openrouter/kimi
    description: Logic reviewer
""")
        code = main(["reviewer-meta", "--config", cfg, "--perspective", "correctness"])
        assert code == 0

    def test_unknown_perspective(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
reviewers:
  - name: APOLLO
    perspective: correctness
""")
        code = main(["reviewer-meta", "--config", cfg, "--perspective", "nonexistent"])
        assert code == 2
        captured = capsys.readouterr()
        assert "unknown perspective" in captured.err


class TestModelDefault:
    def test_prints_default(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
model:
  default: openrouter/kimi
reviewers:
  - name: A
    perspective: b
""")
        code = main(["model-default", "--config", cfg])
        assert code == 0
        captured = capsys.readouterr()
        assert "openrouter/kimi" in captured.out


class TestModelPool:
    def test_prints_pool(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
model:
  pool:
    - openrouter/a
    - openrouter/b
reviewers:
  - name: A
    perspective: b
""")
        code = main(["model-pool", "--config", cfg])
        assert code == 0
        captured = capsys.readouterr()
        assert "openrouter/a" in captured.out
        assert "openrouter/b" in captured.out


class TestModelPoolForTier:
    def test_prints_tier_pool(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
model:
  tiers:
    flash:
      - openrouter/flash-a
      - openrouter/flash-b
reviewers:
  - name: A
    perspective: b
""")
        code = main(["model-pool-for-tier", "--config", cfg, "--tier", "flash"])
        assert code == 0
        captured = capsys.readouterr()
        assert captured.out.strip().splitlines() == ["openrouter/flash-a", "openrouter/flash-b"]

    def test_unknown_tier_prints_nothing(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
model:
  tiers:
    standard:
      - openrouter/standard-a
reviewers:
  - name: A
    perspective: b
""")
        code = main(["model-pool-for-tier", "--config", cfg, "--tier", "missing"])
        assert code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == ""

    def test_empty_tier_is_error(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
model:
  tiers:
    standard:
      - openrouter/standard-a
reviewers:
  - name: A
    perspective: b
""")
        code = main(["model-pool-for-tier", "--config", cfg, "--tier", ""])
        assert code == 2
        captured = capsys.readouterr()
        assert "--tier must be non-empty" in captured.err


class TestConfigError:
    def test_bad_config_file(self, tmp_path, capsys):
        code = main(["model-default", "--config", str(tmp_path / "missing.yml")])
        assert code == 2
        captured = capsys.readouterr()
        assert "defaults config error" in captured.err
