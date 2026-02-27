"""Tests for scripts/evaluate-wave-gate.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "evaluate-wave-gate.py"

spec = importlib.util.spec_from_file_location("evaluate_wave_gate_script", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def _write_config(
    tmp_path: Path,
    *,
    block_on_critical: bool = True,
    block_on_major: bool = True,
    block_on_skip: bool = True,
    skip_tolerance: int = 0,
) -> Path:
    config = tmp_path / "config.yml"
    config.write_text(
        "\n".join(
            [
                "waves:",
                "  enabled: true",
                "  order: [wave1, wave2, wave3]",
                "  max_for_tier:",
                "    flash: 2",
                "    standard: 3",
                "  gate:",
                f"    block_on_critical: {'true' if block_on_critical else 'false'}",
                f"    block_on_major: {'true' if block_on_major else 'false'}",
                f"    block_on_skip: {'true' if block_on_skip else 'false'}",
                f"    skip_tolerance: {skip_tolerance}",
                "  definitions:",
                "    wave1:",
                "      reviewers: [trace]",
                "    wave2:",
                "      reviewers: [atlas]",
                "    wave3:",
                "      reviewers: [guard]",
                "reviewers:",
                "  - name: trace",
                "    perspective: correctness",
                "  - name: atlas",
                "    perspective: architecture",
                "  - name: guard",
                "    perspective: security",
                "",
            ]
        )
    )
    return config


def _write_verdict(
    verdict_dir: Path,
    *,
    verdict: str = "PASS",
    major: int = 0,
    critical: int = 0,
) -> None:
    verdict_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "reviewer": "trace",
        "perspective": "correctness",
        "verdict": verdict,
        "confidence": 0.9,
        "summary": "ok",
        "findings": [],
        "stats": {
            "files_reviewed": 1,
            "files_with_issues": 0,
            "critical": critical,
            "major": major,
            "minor": 0,
            "info": 0,
        },
    }
    (verdict_dir / "trace.json").write_text(json.dumps(payload))


def test_blocks_escalation_on_major(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    verdict_dir = tmp_path / "verdicts"
    _write_verdict(verdict_dir, verdict="WARN", major=1)

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave1", tier="standard")
    assert result["escalate"] is False
    assert result["blocking"] is True
    assert "major_findings" in result["reason"]


def test_escalates_when_gate_passes(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    verdict_dir = tmp_path / "verdicts"
    _write_verdict(verdict_dir, verdict="PASS")

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave1", tier="standard")
    assert result["escalate"] is True
    assert result["blocking"] is False
    assert result["next_wave"] == "wave2"


def test_stops_at_depth_limit_for_flash_tier(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    verdict_dir = tmp_path / "verdicts"
    _write_verdict(verdict_dir, verdict="PASS")

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave2", tier="flash")
    assert result["escalate"] is False
    assert result["blocking"] is False
    assert result["reason"] == "max_wave_reached"


def test_blocks_escalation_on_skip_when_configured(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    verdict_dir = tmp_path / "verdicts"
    _write_verdict(verdict_dir, verdict="SKIP")

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave1", tier="standard")
    assert result["escalate"] is False
    assert result["blocking"] is True
    assert "skip_verdicts" in result["reason"]


def test_major_and_critical_do_not_block_when_gate_flags_disabled(tmp_path: Path) -> None:
    config = _write_config(tmp_path, block_on_major=False, block_on_critical=False)
    verdict_dir = tmp_path / "verdicts"
    _write_verdict(verdict_dir, verdict="WARN", major=2, critical=1)

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave1", tier="standard")
    assert result["blocking"] is False
    assert result["escalate"] is True
    assert result["reason"] == "passed_gate"


def test_count_findings_handles_non_list_and_case_insensitive_matches() -> None:
    assert mod._count_findings({"findings": "not-a-list"}, "major") == 0
    verdict = {"findings": [{"severity": "MAJOR"}, {"severity": "major"}, "x", {"severity": "critical"}]}
    assert mod._count_findings(verdict, "major") == 2


def test_int_or_zero_handles_invalid_values() -> None:
    assert mod._int_or_zero("7") == 7
    assert mod._int_or_zero("bad") == 0
    assert mod._int_or_zero(None) == 0


def test_resolve_wave_depth_unknown_wave_raises(tmp_path: Path) -> None:
    cfg = mod.load_defaults_config(_write_config(tmp_path))
    with pytest.raises(ValueError, match="unknown wave"):
        mod._resolve_wave_depth(cfg, "waveX", "standard")


def test_resolve_wave_depth_non_positive_max_uses_full_order(tmp_path: Path) -> None:
    cfg = mod.load_defaults_config(_write_config(tmp_path))
    cfg.waves.max_for_tier["flash"] = 0
    can_advance, next_wave = mod._resolve_wave_depth(cfg, "wave1", "flash")
    assert can_advance is True
    assert next_wave == "wave2"


def test_evaluate_gate_waves_disabled_returns_disabled_reason(tmp_path: Path) -> None:
    config = tmp_path / "config-disabled.yml"
    config.write_text(
        "\n".join(
            [
                "waves:",
                "  enabled: false",
                "  order: [wave1]",
                "  max_for_tier:",
                "    flash: 2",
                "    standard: 3",
                "  gate:",
                "    block_on_critical: true",
                "    block_on_major: true",
                "    block_on_skip: true",
                "  definitions:",
                "    wave1:",
                "      reviewers: [trace]",
                "reviewers:",
                "  - name: trace",
                "    perspective: correctness",
                "",
            ]
        )
    )
    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=tmp_path / "verdicts", wave="wave1", tier="standard")
    assert result["reason"] == "waves_disabled"
    assert result["stats"]["review_count"] == 0
    assert result["escalate"] is False


def test_evaluate_gate_blocks_on_malformed_and_no_valid_verdicts(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    verdict_dir = tmp_path / "verdicts"
    verdict_dir.mkdir(parents=True, exist_ok=True)
    (verdict_dir / "bad.json").write_text("{not-json")
    (verdict_dir / "array.json").write_text(json.dumps([1, 2, 3]))

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave1", tier="standard")
    assert result["escalate"] is False
    assert result["blocking"] is True
    assert "malformed_artifacts" in result["reason"]
    assert "no_valid_verdicts" in result["reason"]


def test_evaluate_gate_blocks_on_empty_verdict_dir(tmp_path: Path) -> None:
    # An empty verdict dir means wave1 produced no signal (e.g. artifact name mismatch).
    # Escalating vacuously would promote to wave2 on zero evidence — wrong.
    config = _write_config(tmp_path)
    verdict_dir = tmp_path / "verdicts"
    verdict_dir.mkdir(parents=True, exist_ok=True)

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave1", tier="standard")
    assert result["escalate"] is False
    assert result["blocking"] is True
    assert result["reason"] == "no_verdicts"


def test_main_errors_on_empty_wave(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _write_config(tmp_path)
    verdict_dir = tmp_path / "verdicts"
    verdict_dir.mkdir(parents=True, exist_ok=True)
    code = mod.main(
        ["--config", str(config), "--verdict-dir", str(verdict_dir), "--wave", "   ", "--tier", "standard"]
    )
    assert code == 2
    assert "--wave must be non-empty" in capsys.readouterr().err


def test_main_errors_on_config_load(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    verdict_dir = tmp_path / "verdicts"
    verdict_dir.mkdir(parents=True, exist_ok=True)
    code = mod.main(
        [
            "--config",
            str(tmp_path / "missing.yml"),
            "--verdict-dir",
            str(verdict_dir),
            "--wave",
            "wave1",
            "--tier",
            "standard",
        ]
    )
    assert code == 2
    assert "wave gate error:" in capsys.readouterr().err


def test_main_errors_on_missing_verdict_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _write_config(tmp_path)
    code = mod.main(
        [
            "--config",
            str(config),
            "--verdict-dir",
            str(tmp_path / "missing-dir"),
            "--wave",
            "wave1",
            "--tier",
            "standard",
        ]
    )
    assert code == 2
    assert "verdict dir not found" in capsys.readouterr().err


def test_main_errors_on_unknown_wave(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _write_config(tmp_path)
    verdict_dir = tmp_path / "verdicts"
    _write_verdict(verdict_dir, verdict="PASS")
    code = mod.main(
        ["--config", str(config), "--verdict-dir", str(verdict_dir), "--wave", "waveX", "--tier", "standard"]
    )
    assert code == 2
    assert "unknown wave" in capsys.readouterr().err


def test_main_writes_output_json_and_prints_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    verdict_dir = tmp_path / "verdicts"
    _write_verdict(verdict_dir, verdict="PASS")
    out_path = tmp_path / "out" / "gate.json"
    code = mod.main(
        [
            "--config",
            str(config),
            "--verdict-dir",
            str(verdict_dir),
            "--wave",
            "wave1",
            "--tier",
            "standard",
            "--output-json",
            str(out_path),
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "escalate=true" in captured.out
    assert "reason=passed_gate" in captured.out
    data = json.loads(out_path.read_text())
    assert data["wave"] == "wave1"
    assert data["escalate"] is True


# --- skip_tolerance tests ---


def _write_multi_verdict(
    verdict_dir: Path,
    verdicts: list[str],
) -> None:
    """Write multiple verdict files for multi-reviewer wave tests."""
    verdict_dir.mkdir(parents=True, exist_ok=True)
    perspectives = ["trace", "guard", "proof"]
    for i, v in enumerate(verdicts):
        name = perspectives[i] if i < len(perspectives) else f"reviewer{i}"
        payload = {
            "reviewer": name,
            "perspective": name,
            "verdict": v,
            "confidence": 0.9,
            "summary": "ok",
            "findings": [],
            "stats": {
                "files_reviewed": 1,
                "files_with_issues": 0,
                "critical": 0,
                "major": 0,
                "minor": 0,
                "info": 0,
            },
        }
        (verdict_dir / f"{name}.json").write_text(json.dumps(payload))


def test_skip_tolerance_zero_blocks_on_one_skip(tmp_path: Path) -> None:
    """Default tolerance=0: any SKIP is blocking."""
    config = _write_config(tmp_path, skip_tolerance=0)
    verdict_dir = tmp_path / "verdicts"
    _write_multi_verdict(verdict_dir, ["PASS", "PASS", "SKIP"])

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave1", tier="standard")
    assert result["blocking"] is True
    assert "skip_verdicts" in result["reason"]
    assert result["escalate"] is False


def test_skip_tolerance_one_allows_one_skip(tmp_path: Path) -> None:
    """tolerance=1: 1 SKIP out of 3 reviewers escalates instead of blocking."""
    config = _write_config(tmp_path, skip_tolerance=1)
    verdict_dir = tmp_path / "verdicts"
    _write_multi_verdict(verdict_dir, ["PASS", "PASS", "SKIP"])

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave1", tier="standard")
    assert result["blocking"] is False
    assert result["escalate"] is True
    assert result["reason"] == "passed_gate"


def test_skip_tolerance_one_blocks_on_two_skips(tmp_path: Path) -> None:
    """tolerance=1: 2 SKIPs out of 3 reviewers is still blocking."""
    config = _write_config(tmp_path, skip_tolerance=1)
    verdict_dir = tmp_path / "verdicts"
    _write_multi_verdict(verdict_dir, ["PASS", "SKIP", "SKIP"])

    cfg = mod.load_defaults_config(config)
    result = mod.evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave="wave1", tier="standard")
    assert result["blocking"] is True
    assert "skip_verdicts" in result["reason"]
    assert result["escalate"] is False


def test_skip_tolerance_config_loaded_correctly(tmp_path: Path) -> None:
    """Loader persists skip_tolerance into WaveGateConfig."""
    config = _write_config(tmp_path, skip_tolerance=2)
    cfg = mod.load_defaults_config(config)
    assert cfg.waves.gate.skip_tolerance == 2


def test_skip_tolerance_default_is_zero(tmp_path: Path) -> None:
    """When skip_tolerance is absent from config, default is 0."""
    config = tmp_path / "config-no-tol.yml"
    config.write_text(
        "\n".join([
            "waves:",
            "  enabled: true",
            "  order: [wave1, wave2, wave3]",
            "  max_for_tier:",
            "    standard: 3",
            "  gate:",
            "    block_on_skip: true",
            "  definitions:",
            "    wave1:",
            "      reviewers: [trace]",
            "    wave2:",
            "      reviewers: [atlas]",
            "    wave3:",
            "      reviewers: [guard]",
            "reviewers:",
            "  - name: trace",
            "    perspective: correctness",
            "  - name: atlas",
            "    perspective: architecture",
            "  - name: guard",
            "    perspective: security",
            "",
        ])
    )
    cfg = mod.load_defaults_config(config)
    assert cfg.waves.gate.skip_tolerance == 0
