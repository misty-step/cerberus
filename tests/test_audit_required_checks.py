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
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit_required_checks = _load_module()
RepoProtection = audit_required_checks.RepoProtection
RepoRef = audit_required_checks.RepoRef
RequiredCheck = audit_required_checks.RequiredCheck


def test_build_patch_payload_replaces_only_matching_check():
    protection = RepoProtection(
        repo="misty-step/cerberus",
        branch="master",
        strict=True,
        checks=(RequiredCheck("CI"), RequiredCheck("review / Cerberus")),
    )

    payload = audit_required_checks.build_patch_payload(protection, "merge-gate", "CI")

    assert payload == {
        "strict": True,
        "checks": [{"context": "merge-gate"}, {"context": "review / Cerberus"}],
    }


def test_build_patch_command_uses_required_status_checks_endpoint():
    protection = RepoProtection(
        repo="misty-step/cerberus",
        branch="master",
        strict=True,
        checks=(RequiredCheck("CI"),),
    )

    command = audit_required_checks.build_patch_command(protection, "merge-gate", "CI")

    assert "repos/misty-step/cerberus/branches/master/protection/required_status_checks" in command
    assert '"checks":[{"context":"merge-gate"}]' in command


def test_build_patch_command_url_encodes_branch_names():
    protection = RepoProtection(
        repo="misty-step/cerberus",
        branch="release/v1 beta",
        strict=True,
        checks=(RequiredCheck("CI"),),
    )

    command = audit_required_checks.build_patch_command(protection, "merge-gate", "CI")

    assert "branches/release%2Fv1%20beta/protection/required_status_checks" in command


def test_build_patch_command_warns_for_app_scoped_checks():
    protection = RepoProtection(
        repo="misty-step/cerberus",
        branch="master",
        strict=True,
        checks=(RequiredCheck("CI", app_id=12345),),
        has_app_scoped_checks=True,
    )

    command = audit_required_checks.build_patch_command(protection, "merge-gate", "CI")

    assert command.startswith("# warning: repo uses app-scoped required checks")


def test_format_markdown_report_counts_matching_repos():
    protections = [
        RepoProtection(
            repo="misty-step/cerberus",
            branch="master",
            strict=True,
            checks=(RequiredCheck("CI"),),
        ),
        RepoProtection(
            repo="misty-step/chrondle",
            branch="master",
            strict=True,
            checks=(RequiredCheck("build"), RequiredCheck("test")),
        ),
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
        RepoProtection(
            repo="misty-step/cerberus",
            branch="master",
            strict=True,
            checks=(RequiredCheck("merge-gate"),),
        ),
        RepoProtection(
            repo="misty-step/chrondle",
            branch="master",
            strict=True,
            checks=(RequiredCheck("build"), RequiredCheck("test")),
        ),
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


def test_run_gh_raises_when_cli_times_out(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise audit_required_checks.subprocess.TimeoutExpired(cmd="gh", timeout=30)

    monkeypatch.setattr(audit_required_checks.subprocess, "run", fake_run)

    with pytest.raises(audit_required_checks.GHError, match="timed out"):
        audit_required_checks.run_gh(["repo", "list"])


def test_load_json_decodes_run_gh_output(monkeypatch):
    monkeypatch.setattr(audit_required_checks, "run_gh", lambda _args: '{"ok": true}')

    assert audit_required_checks.load_json(["api"]) == {"ok": True}


def test_load_json_wraps_invalid_json(monkeypatch):
    monkeypatch.setattr(audit_required_checks, "run_gh", lambda _args: "{")

    with pytest.raises(audit_required_checks.GHError, match="invalid JSON"):
        audit_required_checks.load_json(["api"])


def test_list_repos_ignores_missing_branch_data(monkeypatch):
    payload = [
        {
            "nameWithOwner": "misty-step/active",
            "defaultBranchRef": {"name": "master"},
            "isArchived": False,
        },
        "bad-entry",
        {
            "nameWithOwner": "misty-step/no-branch",
            "defaultBranchRef": None,
            "isArchived": False,
        },
    ]

    monkeypatch.setattr(audit_required_checks, "load_json", lambda _args: payload)

    repos = audit_required_checks.list_repos("misty-step", 10, include_archived=False)

    assert repos == [RepoRef(repo="misty-step/active", branch="master", archived=False)]


def test_list_repos_rejects_non_list_payload(monkeypatch):
    monkeypatch.setattr(audit_required_checks, "load_json", lambda _args: {"oops": True})

    with pytest.raises(audit_required_checks.GHError, match="non-list JSON"):
        audit_required_checks.list_repos("misty-step", 10, include_archived=False)


def test_get_branch_protection_returns_none_when_gh_fails(monkeypatch):
    def raise_error(_args):
        raise audit_required_checks.GHError("404 Not Found")

    monkeypatch.setattr(audit_required_checks, "load_json", raise_error)

    assert audit_required_checks.get_branch_protection("misty-step/cerberus", "master") is None


def test_get_branch_protection_reraises_non_404_errors(monkeypatch):
    def raise_error(_args):
        raise audit_required_checks.GHError("403 Forbidden")

    monkeypatch.setattr(audit_required_checks, "load_json", raise_error)

    with pytest.raises(audit_required_checks.GHError, match="403 Forbidden"):
        audit_required_checks.get_branch_protection("misty-step/cerberus", "master")


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
        checks=(RequiredCheck("merge-gate"), RequiredCheck("review / Cerberus")),
        has_app_scoped_checks=False,
    )


def test_get_branch_protection_flags_app_scoped_checks(monkeypatch):
    payload = {
        "required_status_checks": {
            "strict": True,
            "contexts": [],
            "checks": [{"context": "merge-gate", "app_id": 12345}],
        }
    }

    monkeypatch.setattr(audit_required_checks, "load_json", lambda _args: payload)

    protection = audit_required_checks.get_branch_protection("misty-step/cerberus", "master")

    assert protection is not None
    assert protection.has_app_scoped_checks is True
    assert protection.checks == (RequiredCheck("merge-gate", app_id=12345),)


def test_get_branch_protection_url_encodes_branch_name(monkeypatch):
    captured = {}

    def fake_load_json(args):
        captured["args"] = args
        return {"required_status_checks": {"strict": True, "contexts": ["merge-gate"]}}

    monkeypatch.setattr(audit_required_checks, "load_json", fake_load_json)

    protection = audit_required_checks.get_branch_protection("misty-step/cerberus", "release/v1 beta")

    assert protection is not None
    assert captured["args"] == ["api", "repos/misty-step/cerberus/branches/release%2Fv1%20beta/protection"]


def test_build_patch_payload_preserves_app_binding():
    protection = RepoProtection(
        repo="misty-step/cerberus",
        branch="master",
        strict=True,
        checks=(RequiredCheck("CI", app_id=12345),),
        has_app_scoped_checks=True,
    )

    payload = audit_required_checks.build_patch_payload(protection, "merge-gate", "CI")

    assert payload == {
        "strict": True,
        "checks": [{"context": "merge-gate", "app_id": 12345}],
    }


def test_get_branch_protection_rejects_non_dict_payload(monkeypatch):
    monkeypatch.setattr(audit_required_checks, "load_json", lambda _args: [])

    with pytest.raises(audit_required_checks.GHError, match="not a JSON object"):
        audit_required_checks.get_branch_protection("misty-step/cerberus", "master")


def test_format_markdown_report_handles_no_ambiguous_or_matching_repos():
    report = audit_required_checks.format_markdown_report(
        [
            RepoProtection(
                repo="misty-step/cerberus",
                branch="master",
                strict=True,
                checks=(RequiredCheck("merge-gate"),),
            )
        ],
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


def test_positive_int_rejects_zero():
    with pytest.raises(audit_required_checks.argparse.ArgumentTypeError, match=">= 1"):
        audit_required_checks.positive_int("0")


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
            checks=(RequiredCheck("CI"),),
        ),
    )

    assert audit_required_checks.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["repos_requiring_match_check"] == 1
    assert payload["protections"][0]["checks"] == [{"context": "CI", "app_id": None}]
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
            checks=(RequiredCheck("merge-gate"),),
        ),
    )

    assert audit_required_checks.main() == 0

    out = capsys.readouterr().out
    assert "## Required Check Audit" in out
    assert "- repos with ambiguous check names: 0" in out


def test_main_returns_error_when_repo_listing_fails(monkeypatch, capsys):
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
            json=False,
        ),
    )
    monkeypatch.setattr(
        audit_required_checks,
        "list_repos",
        lambda _org, _limit, include_archived: (_ for _ in ()).throw(audit_required_checks.GHError("boom")),
    )

    assert audit_required_checks.main() == 1
    assert "failed to list repos" in capsys.readouterr().err


def test_main_warns_and_skips_repo_level_failures(monkeypatch, capsys):
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
        lambda _repo, _branch: (_ for _ in ()).throw(audit_required_checks.GHError("403 Forbidden")),
    )

    assert audit_required_checks.main() == 0
    assert "warning: skipping misty-step/cerberus: 403 Forbidden" in capsys.readouterr().err
