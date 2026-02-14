import json
import subprocess
import sys
from pathlib import Path

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
