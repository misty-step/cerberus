#!/usr/bin/env python3
"""Build a context bundle from a PR diff and metadata.

Splits a unified diff into per-file diffs on disk, generates a manifest
and summary for focused review without inline diff injection.

Usage:
    build-context.py <diff-file> <output-dir> [--pr-context <json-file>]

Output structure:
    <output-dir>/
        manifest.json     # File list with paths, sizes, omission flags
        metadata.json     # PR metadata (title, author, branches)
        summary.md        # Human-readable overview for prompt injection
        diffs/            # Per-file diff files
            <sanitized>.diff
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

# --- Omission heuristics ---

MAX_DIFF_LINES = 500
MAX_DIFF_BYTES = 50_000

SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Gemfile.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "poetry.lock",
}

SKIP_GLOBS = ("*.generated.*", "*.min.js", "*.min.css")

VENDOR_DIRS = (
    "vendor/",
    "node_modules/",
    "dist/",
    "build/",
    ".venv/",
    "__pycache__/",
    ".next/",
)

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2",
    ".wasm", ".map", ".pyc",
}

EXT_LANGUAGES = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".cs": "C#",
    ".php": "PHP",
    ".sh": "Shell",
    ".yml": "YAML",
    ".yaml": "YAML",
}


def _normalize_path(token: str) -> str:
    if token.startswith("a/") or token.startswith("b/"):
        return token[2:]
    return token


def _extract_path(diff_header: str) -> str:
    try:
        parts = shlex.split(diff_header.strip())
    except ValueError:
        parts = diff_header.strip().split()
    if len(parts) < 4:
        return ""
    before_path = _normalize_path(parts[2])
    after_path = _normalize_path(parts[3])
    if after_path and after_path != "/dev/null":
        return after_path
    return before_path


def _sanitize_filename(path: str) -> str:
    """Flatten a file path into a safe filename for the diffs/ directory."""
    return path.replace("/", "__").replace("\\", "__")


def _detect_status(hunk_lines: list[str]) -> str:
    """Detect file status from diff hunk: added, deleted, or modified."""
    for line in hunk_lines:
        if line.startswith("--- /dev/null"):
            return "added"
        if line.startswith("+++ /dev/null"):
            return "deleted"
    return "modified"


def _should_skip_filename(path: str) -> bool:
    import fnmatch
    filename = Path(path).name
    if filename in SKIP_FILENAMES:
        return True
    return any(fnmatch.fnmatch(filename, pat) for pat in SKIP_GLOBS)


def _is_vendor_path(path: str) -> bool:
    return any(path.startswith(d) or f"/{d}" in path for d in VENDOR_DIRS)


def _is_binary_extension(path: str) -> bool:
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def _split_diff(diff_text: str) -> list[tuple[str, list[str]]]:
    """Split a unified diff into (header_line, all_lines) per file."""
    file_hunks: list[tuple[str, list[str]]] = []
    current_header = ""
    current_lines: list[str] = []

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_header:
                file_hunks.append((current_header, current_lines))
            current_header = line
            current_lines = [line]
        elif current_header:
            current_lines.append(line)

    if current_header:
        file_hunks.append((current_header, current_lines))

    return file_hunks


def _detect_stack(changed_files: list[str]) -> str:
    """Detect project stack from changed file extensions and project files."""
    languages: set[str] = set()
    for path in changed_files:
        suffix = Path(path).suffix.lower()
        if suffix in EXT_LANGUAGES:
            languages.add(EXT_LANGUAGES[suffix])
        if Path(path).name == "Dockerfile":
            languages.add("Dockerfile")

    frameworks: set[str] = set()
    root = Path(".")

    package_json = root / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text())
            deps: dict[str, str] = {}
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                deps.update(pkg.get(key, {}) or {})
        except Exception:
            deps = {}
        if "next" in deps:
            frameworks.add("Next.js")
        elif "react" in deps:
            frameworks.add("React")
        for name, fw in [("vue", "Vue"), ("svelte", "Svelte"),
                         ("express", "Express"), ("fastify", "Fastify")]:
            if name in deps:
                frameworks.add(fw)

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(errors="ignore").lower()
        for name, fw in [("django", "Django"), ("fastapi", "FastAPI"),
                         ("flask", "Flask")]:
            if name in text:
                frameworks.add(fw)

    if (root / "go.mod").exists():
        frameworks.add("Go modules")
    if (root / "Cargo.toml").exists():
        frameworks.add("Rust/Cargo")
    if (root / "Gemfile").exists():
        text = (root / "Gemfile").read_text(errors="ignore").lower()
        frameworks.add("Rails" if "rails" in text else "Ruby")

    parts = []
    if languages:
        parts.append("Languages: " + ", ".join(sorted(languages)))
    if frameworks:
        parts.append("Frameworks/runtime: " + ", ".join(sorted(frameworks)))
    return " | ".join(parts) if parts else "Unknown"


def build_context(
    diff_file: Path,
    output_dir: Path,
    pr_context_file: Path | None = None,
) -> dict:
    """Build the context bundle. Returns the manifest dict."""
    diffs_dir = output_dir / "diffs"
    diffs_dir.mkdir(parents=True, exist_ok=True)

    diff_text = diff_file.read_text(errors="ignore")
    file_hunks = _split_diff(diff_text)

    # Load PR metadata
    metadata: dict = {}
    if pr_context_file and pr_context_file.exists():
        try:
            metadata = json.loads(pr_context_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    manifest_files: list[dict] = []
    included_paths: list[str] = []
    omitted_count = 0
    filtered_count = 0

    for header, lines in file_hunks:
        path = _extract_path(header)
        if not path:
            continue

        hunk_text = "".join(lines)
        hunk_lines = len(lines)
        hunk_bytes = len(hunk_text.encode("utf-8", errors="ignore"))
        status = _detect_status(lines)

        # Determine omission reason (if any)
        omit_reason = None
        if _should_skip_filename(path):
            omit_reason = "lockfile_or_generated"
            filtered_count += 1
        elif _is_vendor_path(path):
            omit_reason = "vendor_directory"
            filtered_count += 1
        elif _is_binary_extension(path):
            omit_reason = "binary_file"
            filtered_count += 1
        elif hunk_lines > MAX_DIFF_LINES:
            omit_reason = f"too_large ({hunk_lines} lines, limit {MAX_DIFF_LINES})"
            omitted_count += 1
        elif hunk_bytes > MAX_DIFF_BYTES:
            omit_reason = f"too_large ({hunk_bytes} bytes, limit {MAX_DIFF_BYTES})"
            omitted_count += 1

        entry: dict = {
            "path": path,
            "status": status,
            "diff_lines": hunk_lines,
            "diff_bytes": hunk_bytes,
        }

        if omit_reason:
            entry["omitted"] = True
            entry["omit_reason"] = omit_reason
        else:
            # Write per-file diff
            safe_name = _sanitize_filename(path) + ".diff"
            (diffs_dir / safe_name).write_text(hunk_text)
            entry["omitted"] = False
            entry["diff_file"] = f"diffs/{safe_name}"
            included_paths.append(path)

        manifest_files.append(entry)

    # Detect stack
    all_paths = [e["path"] for e in manifest_files]
    stack_context = _detect_stack(all_paths)

    manifest = {
        "total_files": len(manifest_files),
        "included_files": len(included_paths),
        "omitted_files": omitted_count + filtered_count,
        "stack": stack_context,
        "files": manifest_files,
    }

    # Write manifest
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )

    # Write metadata
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )

    # Write summary
    summary_lines = _build_summary(manifest, metadata)
    (output_dir / "summary.md").write_text(summary_lines)

    return manifest


def _build_summary(manifest: dict, metadata: dict) -> str:
    """Generate a human-readable summary for prompt injection."""
    lines = []

    total = manifest["total_files"]
    included = manifest["included_files"]
    omitted = manifest["omitted_files"]

    lines.append(f"{total} files changed ({included} included, {omitted} omitted)")
    lines.append("")

    if manifest.get("stack") and manifest["stack"] != "Unknown":
        lines.append(f"Stack: {manifest['stack']}")
        lines.append("")

    # File list
    for entry in manifest["files"]:
        status_icon = {"added": "+", "deleted": "-", "modified": "~"}.get(
            entry["status"], "?"
        )
        if entry.get("omitted"):
            lines.append(
                f"  {status_icon} {entry['path']} [OMITTED: {entry.get('omit_reason', 'unknown')}]"
            )
        else:
            lines.append(f"  {status_icon} {entry['path']} ({entry['diff_lines']} lines)")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build PR context bundle")
    parser.add_argument("diff_file", type=Path, help="Path to unified diff file")
    parser.add_argument("output_dir", type=Path, help="Output bundle directory")
    parser.add_argument(
        "--pr-context", type=Path, default=None,
        help="Path to PR context JSON file",
    )
    args = parser.parse_args()

    if not args.diff_file.exists():
        print(f"diff file not found: {args.diff_file}", file=sys.stderr)
        sys.exit(2)

    manifest = build_context(args.diff_file, args.output_dir, args.pr_context)

    # Print summary to stdout for CI visibility
    print(
        f"Context bundle: {manifest['total_files']} files "
        f"({manifest['included_files']} included, "
        f"{manifest['omitted_files']} omitted)"
    )


if __name__ == "__main__":
    main()
