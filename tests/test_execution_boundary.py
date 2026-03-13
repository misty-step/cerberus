"""Guardrails for the review execution boundary from ADR 004."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADR_004 = ROOT / "docs" / "adr" / "004-review-execution-boundary.md"
PROTECTED_ENGINE_PATHS = (
    "scripts/bootstrap-review-run.py",
    "scripts/collect-overrides.py",
    "scripts/post-verdict-review.py",
    "scripts/render-review-prompt.py",
    "scripts/run-reviewer.py",
    "scripts/lib/github.py",
    "scripts/lib/github_reviews.py",
    "scripts/lib/review_run_contract.py",
    "scripts/lib/runtime_facade.py",
)


def _literal_starts_with_gh(node: ast.AST) -> bool:
    if isinstance(node, ast.List | ast.Tuple) and node.elts:
        first = node.elts[0]
        return isinstance(first, ast.Constant) and first.value == "gh"
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("gh ")


def _find_raw_gh_subprocess_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if _literal_starts_with_gh(node.args[0]):
            lines.append(node.lineno)
    return sorted(set(lines))


def test_protected_engine_paths_do_not_embed_raw_gh_transport() -> None:
    offenders: list[str] = []
    for rel_path in PROTECTED_ENGINE_PATHS:
        path = ROOT / rel_path
        assert path.exists(), f"Protected execution-boundary path is missing: {rel_path}"
        lines = _find_raw_gh_subprocess_calls(path)
        if lines:
            offenders.append(f"{rel_path}:{','.join(str(line) for line in lines)}")

    assert offenders == [], (
        "Protected engine-path files must route GitHub CLI transport through "
        "scripts/lib/github_platform.py instead of embedding raw gh calls: "
        + "; ".join(offenders)
    )


def test_adr_004_names_the_allowed_extension_points() -> None:
    text = ADR_004.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "extend `scripts/lib/github_platform.py`" in text
    assert "workflow bootstrap" in lowered
    assert "do not add raw `gh` transport directly to engine-path modules" in lowered
