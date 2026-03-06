from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "audit-required-checks.py"
    spec = importlib.util.spec_from_file_location("audit_required_checks", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit_required_checks = _load_module()
RepoProtection = audit_required_checks.RepoProtection


def test_build_patch_payload_replaces_only_matching_check():
    protection = RepoProtection(
        repo="misty-step/cerberus",
        branch="master",
        strict=True,
        checks=("CI", "review / Cerberus"),
    )

    payload = audit_required_checks.build_patch_payload(protection, "merge-gate", "CI")

    assert payload == {"strict": True, "contexts": ["merge-gate", "review / Cerberus"]}


def test_build_patch_command_uses_required_status_checks_endpoint():
    protection = RepoProtection(
        repo="misty-step/cerberus",
        branch="master",
        strict=True,
        checks=("CI",),
    )

    command = audit_required_checks.build_patch_command(protection, "merge-gate", "CI")

    assert "repos/misty-step/cerberus/branches/master/protection/required_status_checks" in command
    assert '"contexts":["merge-gate"]' in command


def test_format_markdown_report_counts_matching_repos():
    protections = [
        RepoProtection(repo="misty-step/cerberus", branch="master", strict=True, checks=("CI",)),
        RepoProtection(repo="misty-step/chrondle", branch="master", strict=True, checks=("build", "test")),
    ]

    report = audit_required_checks.format_markdown_report(
        protections,
        match_check="CI",
        replacement="merge-gate",
    )

    assert "- repos with repo-level required checks: 2" in report
    assert "- repos requiring `CI`: 1" in report
    assert "### `misty-step/cerberus`" in report
    assert "### `misty-step/chrondle`" not in report
