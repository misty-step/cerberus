"""Large-PR review slicing utilities for correctness and security lanes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SMALL_BUCKET_MAX = 100
MEDIUM_BUCKET_MAX = 250
LARGE_BUCKET_MAX = 600
MAX_SLICE_FILES = 2
MAX_SLICE_CHANGED_LINES = 360
SLICE_PERSPECTIVES = {"correctness", "security"}

DOC_EXTENSIONS = {
    ".md",
    ".mdx",
    ".rst",
    ".txt",
    ".adoc",
    ".asciidoc",
    ".org",
}

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".sql",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
}

SECURITY_PATH_HINTS = (
    "auth",
    "token",
    "secret",
    "session",
    "oauth",
    "login",
    "permission",
    "policy",
    "middleware",
    "route",
    "api",
    "webhook",
    "workflow",
    "docker",
    "k8s",
    "deploy",
    "env",
)

CORRECTNESS_PATH_HINTS = (
    "runtime",
    "router",
    "state",
    "queue",
    "retry",
    "date",
    "time",
    "calc",
    "payment",
    "schema",
    "migrat",
    "serial",
    "parser",
    "transaction",
    "review",
    "verdict",
)


@dataclass(frozen=True)
class DiffChunk:
    path: str
    additions: int
    deletions: int
    changed_lines: int
    is_doc: bool
    is_test: bool
    is_code: bool
    diff_text: str


@dataclass(frozen=True)
class ReviewSlicePlan:
    perspective: str
    size_bucket: str
    total_changed_lines: int
    total_files: int
    code_files: int
    slice_applied: bool
    selected_files: list[str]
    deprioritized_files: list[str]
    slice_diff: str


def is_doc_path(path: str) -> bool:
    normalized = path.lower().strip("/")
    name = Path(normalized).name
    ext = Path(normalized).suffix.lower()
    if ext in DOC_EXTENSIONS:
        return True
    if normalized.startswith(("docs/", "doc/")):
        return True
    return name in {"readme", "readme.md", "changelog.md", "license", "contributing.md"}


def is_test_path(path: str) -> bool:
    normalized = path.lower().strip("/")
    name = Path(normalized).name
    if "/test/" in f"/{normalized}/" or "/tests/" in f"/{normalized}/":
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    return normalized.startswith(("test/", "tests/"))


def classify_file(path: str) -> tuple[bool, bool, bool]:
    doc = is_doc_path(path)
    test = is_test_path(path)
    ext = Path(path).suffix.lower()
    if doc or test:
        return (doc, test, False)
    if ext in CODE_EXTENSIONS or ext == "":
        return (False, False, True)
    return (False, False, True)


def classify_size_bucket(total_changed_lines: int) -> str:
    if total_changed_lines <= SMALL_BUCKET_MAX:
        return "small"
    if total_changed_lines <= MEDIUM_BUCKET_MAX:
        return "medium"
    if total_changed_lines <= LARGE_BUCKET_MAX:
        return "large"
    return "xlarge"


def _finalize_chunk(path: str, raw_lines: list[str], additions: int, deletions: int) -> DiffChunk:
    is_doc, is_test, is_code = classify_file(path)
    return DiffChunk(
        path=path,
        additions=additions,
        deletions=deletions,
        changed_lines=additions + deletions,
        is_doc=is_doc,
        is_test=is_test,
        is_code=is_code,
        diff_text="\n".join(raw_lines).rstrip() + "\n",
    )


def parse_diff_chunks(diff_file: Path) -> list[DiffChunk]:
    text = diff_file.read_text(encoding="utf-8", errors="replace")
    chunks: list[DiffChunk] = []
    current_path: str | None = None
    current_lines: list[str] = []
    additions = 0
    deletions = 0

    for line in text.splitlines():
        if line.startswith("diff --git "):
            if current_path is not None:
                chunks.append(_finalize_chunk(current_path, current_lines, additions, deletions))
            parts = line.split()
            current_path = ""
            if len(parts) >= 4:
                current_path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
            current_lines = [line]
            additions = 0
            deletions = 0
            continue

        if current_path is None:
            continue

        if line.startswith("rename to "):
            renamed = line[len("rename to ") :].strip()
            if renamed:
                current_path = renamed

        if line.startswith("+++ "):
            plus_path = line[4:].strip()
            if plus_path.startswith("b/") and len(plus_path) > 2:
                current_path = plus_path[2:]

        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

        current_lines.append(line)

    if current_path is not None:
        chunks.append(_finalize_chunk(current_path, current_lines, additions, deletions))
    return chunks


def _hint_bonus(path: str, hints: tuple[str, ...]) -> int:
    lowered = path.lower()
    return sum(18 for hint in hints if hint in lowered)


def _score_chunk(chunk: DiffChunk, perspective: str) -> int:
    score = min(chunk.changed_lines, 220)
    if chunk.is_code:
        score += 35
    if chunk.is_test:
        score += 8
    if chunk.is_doc:
        score -= 45

    lowered = chunk.path.lower()
    if perspective == "security":
        score += _hint_bonus(lowered, SECURITY_PATH_HINTS)
        if lowered.startswith(".github/workflows/"):
            score += 40
        if Path(lowered).suffix in {".yml", ".yaml", ".sh", ".toml", ".json"}:
            score += 10
    elif perspective == "correctness":
        score += _hint_bonus(lowered, CORRECTNESS_PATH_HINTS)
        if chunk.changed_lines >= 120:
            score += 20

    return score


def plan_review_slice(diff_file: Path, *, perspective: str) -> ReviewSlicePlan:
    diff_text = diff_file.read_text(encoding="utf-8", errors="replace")
    chunks = parse_diff_chunks(diff_file)
    total_changed_lines = sum(chunk.changed_lines for chunk in chunks)
    total_files = len(chunks)
    code_files = sum(1 for chunk in chunks if chunk.is_code)
    size_bucket = classify_size_bucket(total_changed_lines)

    if (
        perspective not in SLICE_PERSPECTIVES
        or size_bucket not in {"large", "xlarge"}
        or code_files == 0
    ):
        return ReviewSlicePlan(
            perspective=perspective,
            size_bucket=size_bucket,
            total_changed_lines=total_changed_lines,
            total_files=total_files,
            code_files=code_files,
            slice_applied=False,
            selected_files=[chunk.path for chunk in chunks],
            deprioritized_files=[],
            slice_diff=diff_text,
        )

    ranked = sorted(
        chunks,
        key=lambda chunk: (_score_chunk(chunk, perspective), chunk.changed_lines, chunk.path),
        reverse=True,
    )

    selected: list[DiffChunk] = []
    selected_changed_lines = 0
    for chunk in ranked:
        if len(selected) >= MAX_SLICE_FILES:
            break
        if selected and selected_changed_lines + chunk.changed_lines > MAX_SLICE_CHANGED_LINES:
            break
        selected.append(chunk)
        selected_changed_lines += chunk.changed_lines

    if not selected:
        selected = ranked[:1]

    selected_paths = [chunk.path for chunk in selected]
    deprioritized = [chunk.path for chunk in chunks if chunk.path not in set(selected_paths)]

    return ReviewSlicePlan(
        perspective=perspective,
        size_bucket=size_bucket,
        total_changed_lines=total_changed_lines,
        total_files=total_files,
        code_files=code_files,
        slice_applied=True,
        selected_files=selected_paths,
        deprioritized_files=deprioritized,
        slice_diff="".join(chunk.diff_text for chunk in selected),
    )
