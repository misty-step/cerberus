from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import non_gha_review_run as mod


def test_main_runs_local_review_lane(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mod, "fetch_pr_diff", lambda repo, pr_number: "diff --git a b\n")
    monkeypatch.setattr(
        mod,
        "fetch_pr_context",
        lambda repo, pr_number, fields=None: {
            "title": "PR",
            "author": {"login": "dev"},
            "headRefName": "feature/branch",
            "baseRefName": "master",
            "body": "desc",
        },
    )

    commands: list[list[str]] = []

    def fake_run_command(args, *, env):
        commands.append(args)
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
    assert commands[-1][1].endswith("aggregate-verdict.py")


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
    monkeypatch.setattr(mod, "fetch_pr_diff", lambda repo, pr_number: (_ for _ in ()).throw(RuntimeError("boom")))

    assert mod.main() == 2
    assert "failed to fetch PR inputs" in capsys.readouterr().err
