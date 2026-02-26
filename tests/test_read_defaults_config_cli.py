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


class TestModelPoolForWave:
    def test_prints_wave_pool(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
model:
  wave_pools:
    wave1:
      - openrouter/cheap-a
      - openrouter/cheap-b
reviewers:
  - name: A
    perspective: b
""")
        code = main(["model-pool-for-wave", "--config", cfg, "--wave", "wave1"])
        assert code == 0
        captured = capsys.readouterr()
        assert captured.out.strip().splitlines() == ["openrouter/cheap-a", "openrouter/cheap-b"]

    def test_empty_wave_is_error(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
reviewers:
  - name: A
    perspective: b
""")
        code = main(["model-pool-for-wave", "--config", cfg, "--wave", ""])
        assert code == 2
        captured = capsys.readouterr()
        assert "--wave must be non-empty" in captured.err


class TestWaveHelpers:
    def test_wave_order_reviewers_and_max(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
waves:
  order: [wave1, wave2]
  max_for_tier:
    flash: 1
  definitions:
    wave1:
      reviewers: [A]
    wave2:
      reviewers: [B]
reviewers:
  - name: A
    perspective: correctness
  - name: B
    perspective: security
""")
        assert main(["wave-order", "--config", cfg]) == 0
        out = capsys.readouterr()
        assert out.out.strip().splitlines() == ["wave1", "wave2"]

        assert main(["wave-reviewers", "--config", cfg, "--wave", "wave2"]) == 0
        out = capsys.readouterr()
        assert out.out.strip().splitlines() == ["B"]

        assert main(["wave-max-for-tier", "--config", cfg, "--tier", "flash"]) == 0
        out = capsys.readouterr()
        assert out.out.strip() == "1"

    def test_wave_reviewers_empty_wave_is_error(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
waves:
  definitions:
    wave1:
      reviewers: [A]
reviewers:
  - name: A
    perspective: correctness
""")
        assert main(["wave-reviewers", "--config", cfg, "--wave", ""]) == 2
        out = capsys.readouterr()
        assert "--wave must be non-empty" in out.err

    def test_wave_reviewers_unknown_wave_prints_nothing(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
waves:
  definitions:
    wave1:
      reviewers: [A]
reviewers:
  - name: A
    perspective: correctness
""")
        assert main(["wave-reviewers", "--config", cfg, "--wave", "wave9"]) == 0
        out = capsys.readouterr()
        assert out.out.strip() == ""

    def test_wave_max_for_tier_empty_tier_is_error(self, tmp_path, capsys):
        cfg = _write_config(tmp_path, """
waves:
  max_for_tier:
    flash: 1
reviewers:
  - name: A
    perspective: correctness
""")
        assert main(["wave-max-for-tier", "--config", cfg, "--tier", ""]) == 2
        out = capsys.readouterr()
        assert "--tier must be non-empty" in out.err


class TestConfigError:
    def test_bad_config_file(self, tmp_path, capsys):
        code = main(["model-default", "--config", str(tmp_path / "missing.yml")])
        assert code == 2
        captured = capsys.readouterr()
        assert "defaults config error" in captured.err
