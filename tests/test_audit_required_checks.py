from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


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
RepoRef = audit_required_checks.RepoRef


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
        flag_ambiguous=False,
    )

    assert "- repos with repo-level required checks: 2" in report
    assert "- repos requiring `CI`: 1" in report
    assert "### `misty-step/cerberus`" in report
    assert "### `misty-step/chrondle`" not in report


def test_format_markdown_report_flags_ambiguous_checks():
    protections = [
        RepoProtection(repo="misty-step/cerberus", branch="master", strict=True, checks=("merge-gate",)),
        RepoProtection(repo="misty-step/chrondle", branch="master", strict=True, checks=("build", "test")),
    ]

    report = audit_required_checks.format_markdown_report(
        protections,
        match_check="CI",
        replacement="merge-gate",
        flag_ambiguous=True,
    )

    assert "- repos with ambiguous check names: 1" in report
    assert "## Ambiguous Check Names" in report
    assert "`misty-step/chrondle`: build, test" in report


def test_list_repos_skips_archived_repos_by_default(monkeypatch):
    payload = [
        {
            "nameWithOwner": "misty-step/active",
            "defaultBranchRef": {"name": "master"},
            "isArchived": False,
        },
        {
            "nameWithOwner": "misty-step/archived",
            "defaultBranchRef": {"name": "master"},
            "isArchived": True,
        },
    ]

    monkeypatch.setattr(audit_required_checks, "load_json", lambda _args: payload)

    repos = audit_required_checks.list_repos("misty-step", 10, include_archived=False)

    assert repos == [RepoRef(repo="misty-step/active", branch="master", archived=False)]


def test_list_repos_can_include_archived_repos(monkeypatch):
    payload = [
        {
            "nameWithOwner": "misty-step/active",
            "defaultBranchRef": {"name": "master"},
            "isArchived": False,
        },
        {
            "nameWithOwner": "misty-step/archived",
            "defaultBranchRef": {"name": "master"},
            "isArchived": True,
        },
    ]

    monkeypatch.setattr(audit_required_checks, "load_json", lambda _args: payload)

    repos = audit_required_checks.list_repos("misty-step", 10, include_archived=True)

    assert repos == [
        RepoRef(repo="misty-step/active", branch="master", archived=False),
        RepoRef(repo="misty-step/archived", branch="master", archived=True),
    ]


def test_run_gh_raises_when_cli_missing(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(audit_required_checks.subprocess, "run", fake_run)

    with pytest.raises(audit_required_checks.GHError, match="gh CLI not found"):
        audit_required_checks.run_gh(["repo", "list"])


def test_run_gh_raises_with_stderr_message(monkeypatch):
    monkeypatch.setattr(
        audit_required_checks.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="boom\n", stdout=""),
    )

    with pytest.raises(audit_required_checks.GHError, match="boom"):
        audit_required_checks.run_gh(["repo", "list"])


def test_load_json_decodes_run_gh_output(monkeypatch):
    monkeypatch.setattr(audit_required_checks, "run_gh", lambda _args: '{"ok": true}')

    assert audit_required_checks.load_json(["api"]) == {"ok": True}


def test_list_repos_ignores_missing_branch_data(monkeypatch):
    payload = [
        {
            "nameWithOwner": "misty-step/active",
            "defaultBranchRef": {"name": "master"},
            "isArchived": False,
        },
        {
            "nameWithOwner": "misty-step/no-branch",
            "defaultBranchRef": None,
            "isArchived": False,
        },
    ]

    monkeypatch.setattr(audit_required_checks, "load_json", lambda _args: payload)

    repos = audit_required_checks.list_repos("misty-step", 10, include_archived=False)

    assert repos == [RepoRef(repo="misty-step/active", branch="master", archived=False)]


def test_get_branch_protection_returns_none_when_gh_fails(monkeypatch):
    def raise_error(_args):
        raise audit_required_checks.GHError("forbidden")

    monkeypatch.setattr(audit_required_checks, "load_json", raise_error)

    assert audit_required_checks.get_branch_protection("misty-step/cerberus", "master") is None


def test_get_branch_protection_combines_contexts_and_checks(monkeypatch):
    payload = {
        "required_status_checks": {
            "strict": True,
            "contexts": ["merge-gate", "merge-gate", ""],
            "checks": [{"context": "review / Cerberus"}, {"context": None}, "bad"],
        }
    }

    monkeypatch.setattr(audit_required_checks, "load_json", lambda _args: payload)

    protection = audit_required_checks.get_branch_protection("misty-step/cerberus", "master")

    assert protection == RepoProtection(
        repo="misty-step/cerberus",
        branch="master",
        strict=True,
        checks=("merge-gate", "review / Cerberus"),
    )


def test_format_markdown_report_handles_no_ambiguous_or_matching_repos():
    report = audit_required_checks.format_markdown_report(
        [RepoProtection(repo="misty-step/cerberus", branch="master", strict=True, checks=("merge-gate",))],
        match_check="CI",
        replacement="merge-gate",
        flag_ambiguous=True,
    )

    assert "- repos requiring `CI`: 0" in report
    assert "- no repos use ambiguous required check names" in report
    assert "- no repos require the legacy check" in report


def test_parse_args_supports_include_archived(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["audit-required-checks.py", "--org", "misty-step", "--include-archived", "--json"],
    )

    args = audit_required_checks.parse_args()

    assert args.org == "misty-step"
    assert args.include_archived is True
    assert args.json is True


def test_main_prints_json_report(monkeypatch, capsys):
    monkeypatch.setattr(
        audit_required_checks,
        "parse_args",
        lambda: SimpleNamespace(
            org="misty-step",
            limit=10,
            match_check="CI",
            replacement="merge-gate",
            include_archived=False,
            flag_ambiguous=False,
            json=True,
        ),
    )
    monkeypatch.setattr(
        audit_required_checks,
        "list_repos",
        lambda _org, _limit, include_archived: [
            RepoRef(repo="misty-step/cerberus", branch="master", archived=include_archived)
        ],
    )
    monkeypatch.setattr(
        audit_required_checks,
        "get_branch_protection",
        lambda _repo, _branch: RepoProtection(
            repo="misty-step/cerberus",
            branch="master",
            strict=True,
            checks=("CI",),
        ),
    )

    assert audit_required_checks.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["repos_requiring_match_check"] == 1
    assert payload["protections"][0]["patch_command"]


def test_main_prints_markdown_report(monkeypatch, capsys):
    monkeypatch.setattr(
        audit_required_checks,
        "parse_args",
        lambda: SimpleNamespace(
            org="misty-step",
            limit=10,
            match_check="CI",
            replacement="merge-gate",
            include_archived=False,
            flag_ambiguous=True,
            json=False,
        ),
    )
    monkeypatch.setattr(
        audit_required_checks,
        "list_repos",
        lambda _org, _limit, include_archived: [
            RepoRef(repo="misty-step/cerberus", branch="master", archived=include_archived)
        ],
    )
    monkeypatch.setattr(
        audit_required_checks,
        "get_branch_protection",
        lambda _repo, _branch: RepoProtection(
            repo="misty-step/cerberus",
            branch="master",
            strict=True,
            checks=("merge-gate",),
        ),
    )

    assert audit_required_checks.main() == 0

    out = capsys.readouterr().out
    assert "## Required Check Audit" in out
    assert "- repos with ambiguous check names: 0" in out
