import json
import subprocess
import sys
from pathlib import Path

from lib.render_findings import render_findings
from lib.render_findings import main as render_findings_main

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "render-findings.py"


def run_render(
    tmp_path: Path,
    verdict: dict,
    *,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str, str]:
    verdict_path = tmp_path / "verdict.json"
    out_path = tmp_path / "findings.md"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    args = [
        sys.executable,
        str(SCRIPT),
        "--verdict-json",
        str(verdict_path),
        "--output",
        str(out_path),
    ]
    if extra_args:
        args.extend(extra_args)

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    body = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    return result.returncode, body, result.stdout, result.stderr


def test_renders_none_when_no_findings(tmp_path: Path) -> None:
    code, body, out, err = run_render(tmp_path, {"findings": []})
    assert code == 0, err
    assert out.strip() == "0"
    assert body.strip() == "- None"


def test_renders_unverified_meta_and_evidence_block(tmp_path: Path) -> None:
    verdict = {
        "findings": [
            {
                "severity": "major",
                "file": "src/app.py",
                "line": 12,
                "title": "[unverified] Example",
                "description": "desc",
                "suggestion": "fix",
                "evidence": "x = 1\nreturn x",
                "_evidence_unverified": True,
                "_evidence_reason": "evidence-mismatch",
            }
        ]
    }
    code, body, out, err = run_render(tmp_path, verdict)
    assert code == 0, err
    assert out.strip() == "1"
    assert "`src/app.py:12`" in body
    assert "_(unverified: evidence-mismatch)_" in body
    assert "<details>" in body
    assert "<summary>Details</summary>" in body
    assert "Evidence:" in body
    assert "```text" in body
    assert "x = 1" in body


def test_renders_blob_links_when_context_provided(tmp_path: Path) -> None:
    verdict = {
        "findings": [
            {
                "severity": "minor",
                "file": "src/app.py",
                "line": 12,
                "title": "Example",
            }
        ]
    }
    code, body, out, err = run_render(
        tmp_path,
        verdict,
        extra_args=[
            "--server",
            "https://github.com",
            "--repo",
            "misty-step/cerberus",
            "--sha",
            "deadbeef",
        ],
    )

    assert code == 0, err
    assert "[`src/app.py:12`](https://github.com/misty-step/cerberus/blob/deadbeef/src/app.py#L12)" in body


def test_render_findings_renders_markdown_with_defaults() -> None:
    lines = render_findings(
        [
            {
                "severity": "minor",
                "file": "src/app.py",
                "line": 12,
                "title": "Example",
                "description": "desc",
                "suggestion": "fix it",
            }
        ],
        server="https://github.com",
        repo="misty-step/cerberus",
        sha="deadbeef",
    )

    assert "[`src/app.py:12`](https://github.com/misty-step/cerberus/blob/deadbeef/src/app.py#L12)" in lines[0]
    assert any(line.strip() == "desc" for line in lines)
    assert any("Suggestion: fix it" in line for line in lines)
    assert "- [`src/app.py:12`]" not in lines


def test_main_renders_output_directly(tmp_path: Path) -> None:
    verdict_path = tmp_path / "verdict.json"
    output_path = tmp_path / "out.md"
    verdict_path.write_text(json.dumps({"findings": []}), encoding="utf-8")

    code = render_findings_main(
        [
            "--verdict-json",
            str(verdict_path),
            "--output",
            str(output_path),
        ]
    )
    body = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert body == "- None"


def test_main_fails_on_invalid_json(tmp_path: Path, capsys) -> None:
    verdict_path = tmp_path / "verdict.json"
    output_path = tmp_path / "out.md"
    verdict_path.write_text("not-json", encoding="utf-8")

    code = render_findings_main(
        [
            "--verdict-json",
            str(verdict_path),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()

    assert code == 1
    assert "failed to read or parse" in captured.err


def test_main_fails_on_non_object_json(tmp_path: Path, capsys) -> None:
    verdict_path = tmp_path / "verdict.json"
    output_path = tmp_path / "out.md"
    verdict_path.write_text("[1, 2, 3]", encoding="utf-8")

    code = render_findings_main(
        ["--verdict-json", str(verdict_path), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert code == 1
    assert "invalid verdict JSON" in captured.err


def test_main_fails_on_missing_file(tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "out.md"

    code = render_findings_main(
        ["--verdict-json", str(tmp_path / "missing.json"), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert code == 1
    assert "failed to read or parse" in captured.err


def test_findings_not_list_treated_as_empty(tmp_path: Path) -> None:
    verdict_path = tmp_path / "verdict.json"
    output_path = tmp_path / "out.md"
    verdict_path.write_text(json.dumps({"findings": "not a list"}), encoding="utf-8")

    code = render_findings_main(
        ["--verdict-json", str(verdict_path), "--output", str(output_path)]
    )

    assert code == 0
    body = output_path.read_text(encoding="utf-8")
    assert body.strip() == "- None"


def test_render_findings_non_dict_finding_skipped() -> None:
    lines = render_findings(
        ["not a dict", {"severity": "minor", "file": "a.py", "line": 1, "title": "ok"}],
        server="https://gh.com",
        repo="org/repo",
        sha="abc",
    )
    assert len(lines) == 1
    assert "ok" in lines[0]


def test_render_findings_invalid_line_number() -> None:
    lines = render_findings(
        [{"severity": "minor", "file": "a.py", "line": "not_a_number", "title": "ok"}],
        server="https://gh.com",
        repo="org/repo",
        sha="abc",
    )
    assert "[`a.py`]" in lines[0]  # no line number appended


def test_render_findings_negative_line_number() -> None:
    lines = render_findings(
        [{"severity": "minor", "file": "a.py", "line": -1, "title": "ok"}],
        server="https://gh.com",
        repo="org/repo",
        sha="abc",
    )
    assert "[`a.py`]" in lines[0]


def test_render_findings_unverified_no_reason() -> None:
    lines = render_findings(
        [{"severity": "minor", "file": "a.py", "line": 1, "title": "ok",
          "_evidence_unverified": True}],
        server="https://gh.com",
        repo="org/repo",
        sha="abc",
    )
    assert "_(unverified)_" in lines[0]


def test_render_findings_no_description_no_suggestion() -> None:
    lines = render_findings(
        [{"severity": "minor", "file": "a.py", "line": 1, "title": "ok"}],
        server="https://gh.com",
        repo="org/repo",
        sha="abc",
    )
    # No details block when no description/suggestion/evidence
    assert not any("<details>" in line for line in lines)


def test_main_write_failure(tmp_path: Path, capsys) -> None:
    verdict_path = tmp_path / "verdict.json"
    verdict_path.write_text(json.dumps({"findings": []}), encoding="utf-8")

    # Point to a non-existent directory so the write fails
    code = render_findings_main(
        ["--verdict-json", str(verdict_path), "--output", str(tmp_path / "no" / "such" / "dir" / "out.md")]
    )
    captured = capsys.readouterr()

    assert code == 1
    assert "failed to write" in captured.err
