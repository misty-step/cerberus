"""Tests for scripts/evaluate-wave-gate.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "evaluate-wave-gate.py"

spec = importlib.util.spec_from_file_location("evaluate_wave_gate_script", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def _write_config(tmp_path: Path) -> Path:
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
                "    block_on_critical: true",
                "    block_on_major: true",
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
