#!/usr/bin/env python3
"""Test the quality report generation."""
import json
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Import directly
exec(open(Path(__file__).parent.parent / "scripts" / "aggregate-verdict.py").read())

# Test data
verdicts = [
    {"reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS", "confidence": 0.85, "runtime_seconds": 45, "model_used": "kimi", "primary_model": "kimi", "fallback_used": False, "summary": "Looks good"},
    {"reviewer": "SENTINEL", "perspective": "security", "verdict": "SKIP", "confidence": 0, "runtime_seconds": 600, "model_used": "minimax", "primary_model": "minimax", "fallback_used": False, "summary": "timeout after 600s"},
    {"reviewer": "ATHENA", "perspective": "architecture", "verdict": "WARN", "confidence": 0.75, "runtime_seconds": 60, "model_used": "glm", "primary_model": "glm", "fallback_used": True, "summary": "Some issues"},
]

council = {"verdict": "WARN", "summary": "test"}

# Test quality report generation
report = generate_quality_report(verdicts, council, [], "misty-step/test", "123", "abc123")

# Validate structure
assert "meta" in report
assert "summary" in report
assert "reviewers" in report
assert "models" in report

assert report["meta"]["repo"] == "misty-step/test"
assert report["summary"]["total_reviewers"] == 3
assert report["summary"]["skip_count"] == 1
assert report["summary"]["skip_rate"] == 1/3
assert report["summary"]["council_verdict"] == "WARN"

# Check model aggregation
assert "kimi" in report["models"]
assert report["models"]["kimi"]["count"] == 1
assert report["models"]["kimi"]["verdicts"]["PASS"] == 1

print("✅ All tests passed!")
print(json.dumps(report, indent=2))
