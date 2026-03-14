"""Tests for scripts.non_gha_review_run orchestration and failure handling."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import non_gha_review_run as mod


def test_parse_args_accepts_explicit_flags(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "non_gha_review_run.py",
            "--repo",
            "misty-step/cerberus",
            "--pr",
            "329",
            "--output-dir",
            "/tmp/artifacts",
            "--reviewers",
            "trace,guard",
            "--token-env-var",
            "TEST_TOKEN",
        ],
    )

    args = mod.parse_args()

    assert args.repo == "misty-step/cerberus"
    assert args.pr == 329
    assert args.output_dir == "/tmp/artifacts"
    assert args.reviewers == "trace,guard"
    assert args.token_env_var == "TEST_TOKEN"


def test_selected_reviewers_uses_defaults_config_when_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "load_defaults_config",
        lambda path: SimpleNamespace(
            reviewers=[SimpleNamespace(name="trace"), SimpleNamespace(name="guard")]
        ),
    )

    assert mod.selected_reviewers("") == ["trace", "guard"]


def test_run_command_delegates_to_subprocess(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = mod.run_command(["python3", "--version"], env={"X": "1"}, timeout_seconds=45)

    assert result.stdout == "ok"
    assert seen["args"] == ["python3", "--version"]
    assert seen["kwargs"] == {
        "cwd": str(mod.ROOT),
        "env": {"X": "1"},
        "text": True,
        "capture_output": True,
        "check": False,
        "timeout": 45,
    }


def test_run_command_raises_runtime_error_on_timeout(monkeypatch) -> None:
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=30)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    try:
        mod.run_command(["python3", "--version"], env={"X": "1"}, timeout_seconds=30)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected run_command to raise")

    assert "command timed out after 30s" in message
    assert "python3 --version" in message


def test_enrich_verdict_metadata_records_runtime_model_and_description(monkeypatch, tmp_path: Path) -> None:
    verdict_path = tmp_path / "trace-verdict.json"
    verdict_path.write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
    (tmp_path / "trace-runtime-seconds").write_text("12\n", encoding="utf-8")
    (tmp_path / "trace-model-used").write_text("openrouter/fallback\n", encoding="utf-8")
    (tmp_path / "trace-primary-model").write_text("openrouter/primary\n", encoding="utf-8")
    (tmp_path / "trace-configured-model").write_text("openrouter/configured\n", encoding="utf-8")
    (tmp_path / "trace-reviewer-desc").write_text("Trace reviewer\n", encoding="utf-8")
    monkeypatch.setenv("MODEL_WAVE", "wave-1")

    mod.enrich_verdict_metadata(output_dir=tmp_path, perspective="trace")

    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["runtime_seconds"] == 12
    assert verdict["model_used"] == "openrouter/fallback"
    assert verdict["primary_model"] == "openrouter/primary"
    assert verdict["configured_model"] == "openrouter/configured"
    assert verdict["fallback_used"] is True
    assert verdict["model_wave"] == "wave-1"
    assert verdict["reviewer_description"] == "Trace reviewer"


def test_main_runs_local_review_lane(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "fetch_pr_bootstrap",
        lambda repo, pr_number: (
            "diff --git a b\n",
            {
                "title": "PR",
                "author": {"login": "dev"},
                "headRefName": "feature/branch",
                "baseRefName": "master",
                "body": "desc",
            },
        ),
    )

    commands: list[tuple[list[str], int]] = []

    def fake_run_command(args, *, env, timeout_seconds):
        commands.append((args, timeout_seconds))
        output_dir = Path(env["CERBERUS_TMP"])

        if args[1].endswith("run-reviewer.sh"):
            perspective = args[-1]
            (output_dir / f"{perspective}-output.txt").write_text(
                "```json\n"
                + json.dumps(
                    {
                        "reviewer": perspective,
                        "perspective": perspective,
                        "verdict": "PASS",
                        "confidence": 0.95,
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
                )
                + "\n```\n",
                encoding="utf-8",
            )
            (output_dir / f"{perspective}-model-used").write_text("openrouter/test-model\n", encoding="utf-8")
            (output_dir / f"{perspective}-primary-model").write_text("openrouter/test-model\n", encoding="utf-8")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        if args[1].endswith("parse-review.py"):
            perspective = env["PERSPECTIVE"]
            verdict = {
                "reviewer": perspective,
                "perspective": perspective,
                "verdict": "PASS",
                "confidence": 0.95,
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
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(verdict),
                stderr="",
            )

        if args[1].endswith("aggregate-verdict.py"):
            (Path(env["CERBERUS_TMP"]) / "verdict.json").write_text(
                json.dumps({"verdict": "PASS", "reviewers": []}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="PASS", stderr="")

        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(mod, "run_command", fake_run_command)
    monkeypatch.setattr(mod, "selected_reviewers", lambda raw: ["trace", "guard"])
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "repo": "misty-step/cerberus",
                "pr": 329,
                "output_dir": str(tmp_path / "artifacts"),
                "reviewers": "",
                "token_env_var": "GH_TOKEN",
            },
        )(),
    )

    assert mod.main() == 0

    out = capsys.readouterr().out.strip()
    assert out == str((tmp_path / "artifacts" / "verdict.json").resolve())
    review_run = json.loads((tmp_path / "artifacts" / "review-run.json").read_text(encoding="utf-8"))
    assert review_run["repository"] == "misty-step/cerberus"
    assert review_run["pr_number"] == 329
    assert review_run["head_ref"] == "feature/branch"
    assert review_run["base_ref"] == "master"
    assert commands[0][1] == mod.DEFAULT_REVIEW_TIMEOUT_SECONDS
    assert commands[-1][0][1].endswith("aggregate-verdict.py")
    assert commands[-1][1] == mod.DEFAULT_HELPER_TIMEOUT_SECONDS
    assert json.loads((tmp_path / "artifacts" / "verdicts" / "trace-verdict.json").read_text())["verdict"] == "PASS"
    assert json.loads((tmp_path / "artifacts" / "verdicts" / "guard-verdict.json").read_text())["verdict"] == "PASS"


def test_run_reviewer_uses_parse_input_override(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, str], int]] = []
    output_dir = tmp_path / "artifacts"
    output_dir.mkdir(parents=True)

    def fake_run_command(args, *, env, timeout_seconds):
        calls.append((args, dict(env), timeout_seconds))
        if args[1].endswith("run-reviewer.sh"):
            parse_input = output_dir / "nested" / "override-output.txt"
            parse_input.parent.mkdir(parents=True, exist_ok=True)
            parse_input.write_text("review output", encoding="utf-8")
            (output_dir / "trace-parse-input").write_text("nested/override-output.txt", encoding="utf-8")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if args[1].endswith("parse-review.py"):
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps({"verdict": "PASS"}),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(mod, "run_command", fake_run_command)
    monkeypatch.setattr(mod.time, "time", lambda: 100.0 if not calls else 103.4)

    mod.run_reviewer(
        perspective="trace",
        output_dir=output_dir,
        base_env={"CERBERUS_TMP": str(output_dir), "CERBERUS_ROOT": "/repo"},
    )

    assert calls[0][1]["PERSPECTIVE"] == "trace"
    assert calls[0][2] == mod.DEFAULT_REVIEW_TIMEOUT_SECONDS
    assert calls[1][0][-1] == str((output_dir / "nested" / "override-output.txt").resolve())
    assert calls[1][2] == mod.DEFAULT_HELPER_TIMEOUT_SECONDS
    assert (output_dir / "trace-runtime-seconds").read_text(encoding="utf-8").strip() == "3"
    assert json.loads((output_dir / "trace-verdict.json").read_text(encoding="utf-8"))["verdict"] == "PASS"


def test_aggregate_verdicts_clears_stale_verdict_artifacts(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "artifacts"
    verdict_dir = output_dir / "verdicts"
    verdict_dir.mkdir(parents=True)
    (verdict_dir / "stale-verdict.json").write_text("{}", encoding="utf-8")
    (output_dir / "trace-verdict.json").write_text("{}", encoding="utf-8")

    seen_env: dict[str, str] = {}

    def fake_run_command(args, *, env, timeout_seconds):
        seen_env.update(env)
        (output_dir / "verdict.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod, "run_command", fake_run_command)

    mod.aggregate_verdicts(
        output_dir=output_dir,
        repo="misty-step/cerberus",
        pr_number=329,
        reviewers=["trace"],
        base_env={"CERBERUS_ROOT": "/repo", "CERBERUS_REVIEW_RUN": "/tmp/review-run.json"},
    )

    assert not (verdict_dir / "stale-verdict.json").exists()
    assert (verdict_dir / "trace-verdict.json").exists()
    assert seen_env["CERBERUS_ROOT"] == "/repo"
    assert seen_env["CERBERUS_REVIEW_RUN"] == "/tmp/review-run.json"


def test_aggregate_verdicts_raises_when_aggregate_verdict_fails(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "artifacts"
    (output_dir / "trace-verdict.json").parent.mkdir(parents=True, exist_ok=True)
    (output_dir / "trace-verdict.json").write_text("{}", encoding="utf-8")

    def fake_run_command(args, *, env, timeout_seconds):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="bad stdout", stderr="bad stderr")

    monkeypatch.setattr(mod, "run_command", fake_run_command)

    try:
        mod.aggregate_verdicts(
            output_dir=output_dir,
            repo="misty-step/cerberus",
            pr_number=329,
            reviewers=["trace"],
            base_env={"CERBERUS_ROOT": "/repo"},
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected aggregate_verdicts to raise")

    assert "aggregate-verdict failed" in message
    assert "bad stdout" in message
    assert "bad stderr" in message


def test_main_returns_two_when_no_reviewers(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "repo": "misty-step/cerberus",
                "pr": 329,
                "output_dir": str(tmp_path / "artifacts"),
                "reviewers": "",
                "token_env_var": "GH_TOKEN",
            },
        )(),
    )
    monkeypatch.setattr(mod, "selected_reviewers", lambda raw: [])

    assert mod.main() == 2
    assert "no reviewers selected" in capsys.readouterr().err


def test_main_returns_two_when_fetch_fails(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "repo": "misty-step/cerberus",
                "pr": 329,
                "output_dir": str(tmp_path / "artifacts"),
                "reviewers": "",
                "token_env_var": "GH_TOKEN",
            },
        )(),
    )
    monkeypatch.setattr(mod, "selected_reviewers", lambda raw: ["trace"])
    monkeypatch.setattr(
        mod,
        "fetch_pr_bootstrap",
        lambda repo, pr_number: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert mod.main() == 2
    assert "failed to fetch PR inputs" in capsys.readouterr().err


def test_main_returns_two_when_pr_context_fetch_fails(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "repo": "misty-step/cerberus",
                "pr": 329,
                "output_dir": str(tmp_path / "artifacts"),
                "reviewers": "",
                "token_env_var": "GH_TOKEN",
            },
        )(),
    )
    monkeypatch.setattr(mod, "selected_reviewers", lambda raw: ["trace"])
    monkeypatch.setattr(
        mod,
        "fetch_pr_bootstrap",
        lambda repo, pr_number: (_ for _ in ()).throw(RuntimeError("context boom")),
    )

    assert mod.main() == 2
    assert "failed to fetch PR inputs" in capsys.readouterr().err


def test_main_returns_one_when_verdict_file_is_missing(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "fetch_pr_bootstrap",
        lambda repo, pr_number: (
            "diff --git a b\n",
            {
                "title": "PR",
                "author": {"login": "dev"},
                "headRefName": "feature/branch",
                "baseRefName": "master",
                "body": "desc",
            },
        ),
    )

    def fake_run_reviewer(*, perspective: str, output_dir: Path, base_env: dict[str, str]) -> None:
        (output_dir / f"{perspective}-verdict.json").write_text("{}", encoding="utf-8")

    def fake_aggregate_verdicts(*, output_dir: Path, repo: str, pr_number: int, reviewers: list[str], base_env: dict[str, str]) -> None:
        return None

    monkeypatch.setattr(mod, "run_reviewer", fake_run_reviewer)
    monkeypatch.setattr(mod, "aggregate_verdicts", fake_aggregate_verdicts)
    monkeypatch.setattr(mod, "selected_reviewers", lambda raw: ["trace"])
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "repo": "misty-step/cerberus",
                "pr": 329,
                "output_dir": str(tmp_path / "artifacts"),
                "reviewers": "",
                "token_env_var": "GH_TOKEN",
            },
        )(),
    )

    assert mod.main() == 1
    assert "verdict.json" in capsys.readouterr().err


def test_main_returns_one_when_run_reviewer_raises_value_error(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "fetch_pr_bootstrap",
        lambda repo, pr_number: (
            "diff --git a b\n",
            {
                "title": "PR",
                "author": {"login": "dev"},
                "headRefName": "feature/branch",
                "baseRefName": "master",
                "body": "desc",
            },
        ),
    )
    monkeypatch.setattr(
        mod,
        "run_reviewer",
        lambda *, perspective, output_dir, base_env: (_ for _ in ()).throw(ValueError("bad verdict payload")),
    )
    monkeypatch.setattr(mod, "selected_reviewers", lambda raw: ["trace"])
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "repo": "misty-step/cerberus",
                "pr": 329,
                "output_dir": str(tmp_path / "artifacts"),
                "reviewers": "",
                "token_env_var": "GH_TOKEN",
            },
        )(),
    )

    assert mod.main() == 1
    assert "bad verdict payload" in capsys.readouterr().err


def test_run_reviewer_rejects_empty_parse_input_override(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    output_dir.mkdir(parents=True)
    (output_dir / "trace-parse-input").write_text("\n", encoding="utf-8")

    def fake_run_command(args, *, env, timeout_seconds):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod, "run_command", fake_run_command)
    monkeypatch.setattr(mod.time, "time", lambda: 100.0)

    try:
        mod.run_reviewer(
            perspective="trace",
            output_dir=output_dir,
            base_env={"CERBERUS_TMP": str(output_dir), "CERBERUS_ROOT": "/repo"},
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected run_reviewer to raise")

    assert "empty parse input override for trace" in message
