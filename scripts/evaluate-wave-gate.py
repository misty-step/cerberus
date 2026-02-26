#!/usr/bin/env python3
"""Evaluate whether Cerberus should escalate from one review wave to the next."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lib.defaults_config import ConfigError, DefaultsConfig, load_defaults_config


def _count_findings(verdict: dict[str, Any], severity: str) -> int:
    findings = verdict.get("findings")
    if not isinstance(findings, list):
        return 0
    count = 0
    for finding in findings:
        if isinstance(finding, dict) and str(finding.get("severity", "")).lower() == severity:
            count += 1
    return count


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_major_and_critical(verdict: dict[str, Any]) -> tuple[int, int]:
    stats = verdict.get("stats")
    major_from_stats = 0
    critical_from_stats = 0
    if isinstance(stats, dict):
        major_from_stats = _int_or_zero(stats.get("major"))
        critical_from_stats = _int_or_zero(stats.get("critical"))

    major_from_findings = _count_findings(verdict, "major")
    critical_from_findings = _count_findings(verdict, "critical")
    major = max(major_from_stats, major_from_findings)
    critical = max(critical_from_stats, critical_from_findings)
    return major, critical


def _resolve_wave_depth(cfg: DefaultsConfig, wave: str, tier: str) -> tuple[bool, str]:
    order = cfg.waves.order
    if wave not in order:
        raise ValueError(f"unknown wave '{wave}'")

    current_index = order.index(wave)
    max_for_tier = cfg.waves.max_for_tier.get(tier, cfg.waves.max_for_tier.get("standard", len(order)))
    if max_for_tier < 1:
        max_for_tier = len(order)
    allowed_last_index = min(max_for_tier, len(order)) - 1

    if current_index >= allowed_last_index:
        return False, ""

    next_wave = order[current_index + 1]
    return True, next_wave


def evaluate_gate(*, cfg: DefaultsConfig, verdict_dir: Path, wave: str, tier: str) -> dict[str, Any]:
    """Evaluate wave gate and return structured decision."""
    if not cfg.waves.enabled:
        return {
            "wave": wave,
            "tier": tier,
            "escalate": False,
            "blocking": False,
            "next_wave": "",
            "reason": "waves_disabled",
            "stats": {
                "review_count": 0,
                "major_count": 0,
                "critical_count": 0,
                "skip_count": 0,
                "malformed_count": 0,
            },
        }

    should_advance_for_depth, next_wave = _resolve_wave_depth(cfg, wave, tier)

    verdict_files = sorted(verdict_dir.glob("*.json"))
    major_total = 0
    critical_total = 0
    skip_count = 0
    malformed_count = 0
    parsed_count = 0

    for file_path in verdict_files:
        try:
            verdict = json.loads(file_path.read_text())
        except (json.JSONDecodeError, OSError):
            malformed_count += 1
            continue

        if not isinstance(verdict, dict):
            malformed_count += 1
            continue

        parsed_count += 1
        major, critical = _extract_major_and_critical(verdict)
        major_total += major
        critical_total += critical

        if str(verdict.get("verdict", "")).upper() == "SKIP":
            skip_count += 1

    blocking_reasons: list[str] = []
    gate = cfg.waves.gate
    if malformed_count > 0:
        blocking_reasons.append("malformed_artifacts")
    if parsed_count == 0 and len(verdict_files) > 0:
        blocking_reasons.append("no_valid_verdicts")
    if gate.block_on_critical and critical_total > 0:
        blocking_reasons.append("critical_findings")
    if gate.block_on_major and major_total > 0:
        blocking_reasons.append("major_findings")
    if gate.block_on_skip and skip_count > 0:
        blocking_reasons.append("skip_verdicts")

    blocking = len(blocking_reasons) > 0
    if blocking:
        escalate = False
        reason = ",".join(blocking_reasons)
        next_wave = ""
    elif not should_advance_for_depth:
        escalate = False
        reason = "max_wave_reached"
        next_wave = ""
    else:
        escalate = True
        reason = "passed_gate"

    return {
        "wave": wave,
        "tier": tier,
        "escalate": escalate,
        "blocking": blocking,
        "next_wave": next_wave,
        "reason": reason,
        "stats": {
            "review_count": parsed_count,
            "major_count": major_total,
            "critical_count": critical_total,
            "skip_count": skip_count,
            "malformed_count": malformed_count,
        },
    }


def main(argv: list[str]) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="evaluate-wave-gate.py")
    parser.add_argument("--config", required=True)
    parser.add_argument("--verdict-dir", required=True)
    parser.add_argument("--wave", required=True)
    parser.add_argument("--tier", required=True)
    parser.add_argument("--output-json", required=False, default="")
    args = parser.parse_args(argv)

    wave = str(args.wave).strip().lower()
    tier = str(args.tier).strip().lower() or "standard"
    if not wave:
        print("wave gate error: --wave must be non-empty", file=sys.stderr)
        return 2

    try:
        cfg = load_defaults_config(Path(args.config))
    except ConfigError as exc:
        print(f"wave gate error: {exc}", file=sys.stderr)
        return 2

    verdict_dir = Path(args.verdict_dir)
    if not verdict_dir.exists():
        print(f"wave gate error: verdict dir not found: {verdict_dir}", file=sys.stderr)
        return 2

    try:
        result = evaluate_gate(cfg=cfg, verdict_dir=verdict_dir, wave=wave, tier=tier)
    except ValueError as exc:
        print(f"wave gate error: {exc}", file=sys.stderr)
        return 2

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2))

    print(f"escalate={'true' if result['escalate'] else 'false'}")
    print(f"blocking={'true' if result['blocking'] else 'false'}")
    print(f"next_wave={result['next_wave']}")
    print(f"reason={result['reason']}")
    print(f"major_count={result['stats']['major_count']}")
    print(f"critical_count={result['stats']['critical_count']}")
    print(f"skip_count={result['stats']['skip_count']}")
    print(f"review_count={result['stats']['review_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
