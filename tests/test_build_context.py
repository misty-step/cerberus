"""Tests for scripts/build-context.py: diff splitting, manifest, omission."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Import build_context functions directly
import importlib.util

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("build_context", SCRIPTS_DIR / "build-context.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_context = _mod.build_context
_split_diff = _mod._split_diff
_sanitize_filename = _mod._sanitize_filename
_extract_path = _mod._extract_path
_detect_status = _mod._detect_status
_build_summary = _mod._build_summary


def _hunk(path: str, added_line: str, *, deleted: bool = False) -> str:
    """Build a minimal unified diff hunk for one file."""
    if deleted:
        return (
            f"diff --git a/{path} b/{path}\n"
            "index 1111111..0000000 100644\n"
            f"--- a/{path}\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            f"-{added_line}\n"
        )
    return (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"+{added_line}\n"
    )


def _new_file_hunk(path: str, content: str) -> str:
    """Build a new file diff hunk."""
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"+{content}\n"
    )


class TestSplitDiff:
    def test_single_file(self):
        diff = _hunk("src/app.py", "print('hello')")
        hunks = _split_diff(diff)
        assert len(hunks) == 1
        assert "app.py" in hunks[0][0]

    def test_multiple_files(self):
        diff = _hunk("a.py", "x") + _hunk("b.py", "y") + _hunk("c.py", "z")
        hunks = _split_diff(diff)
        assert len(hunks) == 3

    def test_empty_diff(self):
        assert _split_diff("") == []
        assert _split_diff("some preamble\n") == []


class TestHelpers:
    def test_sanitize_filename_flattens_path(self):
        assert _sanitize_filename("src/components/Button.tsx") == "src__components__Button.tsx"

    def test_extract_path_normal(self):
        assert _extract_path("diff --git a/foo.py b/foo.py") == "foo.py"

    def test_extract_path_with_directory(self):
        assert _extract_path("diff --git a/src/bar.ts b/src/bar.ts") == "src/bar.ts"

    def test_extract_path_deleted_file(self):
        assert _extract_path("diff --git a/old.py b/old.py") == "old.py"

    def test_detect_status_added(self):
        lines = ["diff --git a/x b/x\n", "--- /dev/null\n", "+++ b/x\n"]
        assert _detect_status(lines) == "added"

    def test_detect_status_deleted(self):
        lines = ["diff --git a/x b/x\n", "--- a/x\n", "+++ /dev/null\n"]
        assert _detect_status(lines) == "deleted"

    def test_detect_status_modified(self):
        lines = ["diff --git a/x b/x\n", "--- a/x\n", "+++ b/x\n"]
        assert _detect_status(lines) == "modified"


class TestBuildContext:
    def test_basic_split(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(
            _hunk("src/app.py", "print('hello')") +
            _hunk("src/utils.py", "def helper(): pass")
        )
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        assert manifest["total_files"] == 2
        assert manifest["included_files"] == 2
        assert manifest["omitted_files"] == 0

        # Per-file diffs exist
        diffs_dir = out / "diffs"
        assert (diffs_dir / "src__app.py.diff").exists()
        assert (diffs_dir / "src__utils.py.diff").exists()

        # Diff content is correct
        app_diff = (diffs_dir / "src__app.py.diff").read_text()
        assert "print('hello')" in app_diff
        assert "utils.py" not in app_diff

    def test_lockfile_omitted(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(
            _hunk("src/app.py", "x") +
            _hunk("package-lock.json", '{"name":"demo"}')
        )
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        assert manifest["included_files"] == 1
        assert manifest["omitted_files"] == 1

        lock_entry = [f for f in manifest["files"] if f["path"] == "package-lock.json"][0]
        assert lock_entry["omitted"] is True
        assert "lockfile" in lock_entry["omit_reason"]

        # Lockfile diff NOT written to disk
        assert not (out / "diffs" / "package-lock.json.diff").exists()

    def test_generated_file_omitted(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(
            _hunk("src/app.py", "x") +
            _hunk("types.generated.ts", "export type X = string;")
        )
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        gen_entry = [f for f in manifest["files"] if "generated" in f["path"]][0]
        assert gen_entry["omitted"] is True

    def test_minified_file_omitted(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(
            _hunk("src/app.py", "x") +
            _hunk("bundle.min.js", "var x=1;")
        )
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        min_entry = [f for f in manifest["files"] if "min.js" in f["path"]][0]
        assert min_entry["omitted"] is True

    def test_vendor_directory_omitted(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(
            _hunk("src/app.py", "x") +
            _hunk("vendor/lib/foo.go", "package foo")
        )
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        vendor_entry = [f for f in manifest["files"] if "vendor" in f["path"]][0]
        assert vendor_entry["omitted"] is True
        assert "vendor" in vendor_entry["omit_reason"]

    def test_binary_file_omitted(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(
            _hunk("src/app.py", "x") +
            _hunk("assets/logo.png", "binary data")
        )
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        img_entry = [f for f in manifest["files"] if "logo.png" in f["path"]][0]
        assert img_entry["omitted"] is True
        assert "binary" in img_entry["omit_reason"]

    def test_large_diff_omitted(self, tmp_path: Path):
        """Files exceeding 500 lines are omitted from diffs/."""
        diff_file = tmp_path / "pr.diff"
        # 600 lines in a single file
        big_lines = "diff --git a/big.py b/big.py\n"
        big_lines += "--- a/big.py\n+++ b/big.py\n"
        big_lines += "@@ -0,0 +1,600 @@\n"
        big_lines += "".join(f"+line {i}\n" for i in range(600))

        small_hunk = _hunk("src/app.py", "print('ok')")
        diff_file.write_text(small_hunk + big_lines)

        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        big_entry = [f for f in manifest["files"] if f["path"] == "big.py"][0]
        assert big_entry["omitted"] is True
        assert "too_large" in big_entry["omit_reason"]
        assert not (out / "diffs" / "big.py.diff").exists()

        # Small file still included
        small_entry = [f for f in manifest["files"] if f["path"] == "src/app.py"][0]
        assert small_entry["omitted"] is False

    def test_large_bytes_omitted(self, tmp_path: Path):
        """Files exceeding 50KB are omitted from diffs/."""
        diff_file = tmp_path / "pr.diff"
        # Single line >50KB
        big_line = "x" * 60_000
        content = (
            "diff --git a/huge.py b/huge.py\n"
            "--- a/huge.py\n+++ b/huge.py\n"
            "@@ -0,0 +1 @@\n"
            f"+{big_line}\n"
        )
        diff_file.write_text(_hunk("src/app.py", "ok") + content)

        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        huge_entry = [f for f in manifest["files"] if f["path"] == "huge.py"][0]
        assert huge_entry["omitted"] is True
        assert "too_large" in huge_entry["omit_reason"]

    def test_metadata_written(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(_hunk("app.py", "x"))

        pr_ctx = tmp_path / "pr-context.json"
        pr_ctx.write_text(json.dumps({
            "title": "Fix auth bug",
            "author": {"login": "testuser"},
            "headRefName": "fix/auth",
            "baseRefName": "main",
            "body": "Fixes the auth flow",
        }))

        out = tmp_path / "bundle"
        build_context(diff_file, out, pr_ctx)

        metadata = json.loads((out / "metadata.json").read_text())
        assert metadata["title"] == "Fix auth bug"
        assert metadata["author"]["login"] == "testuser"

    def test_metadata_missing_gracefully(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(_hunk("app.py", "x"))

        out = tmp_path / "bundle"
        build_context(diff_file, out)

        metadata = json.loads((out / "metadata.json").read_text())
        assert metadata == {}

    def test_summary_written(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(
            _hunk("src/app.py", "x") +
            _hunk("package-lock.json", "y")
        )
        out = tmp_path / "bundle"
        build_context(diff_file, out)

        summary = (out / "summary.md").read_text()
        assert "2 files changed" in summary
        assert "1 included" in summary
        assert "1 omitted" in summary
        assert "src/app.py" in summary
        assert "OMITTED" in summary

    def test_manifest_json_valid(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(_hunk("foo.py", "pass"))
        out = tmp_path / "bundle"
        build_context(diff_file, out)

        manifest = json.loads((out / "manifest.json").read_text())
        assert "total_files" in manifest
        assert "files" in manifest
        assert isinstance(manifest["files"], list)
        assert manifest["files"][0]["path"] == "foo.py"
        assert "diff_file" in manifest["files"][0]

    def test_new_file_detected_as_added(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(_new_file_hunk("src/new.py", "print('new')"))
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        entry = manifest["files"][0]
        assert entry["status"] == "added"

    def test_deleted_file_detected(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(_hunk("old.py", "removed", deleted=True))
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        entry = manifest["files"][0]
        assert entry["status"] == "deleted"

    def test_empty_diff(self, tmp_path: Path):
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text("")
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        assert manifest["total_files"] == 0
        assert manifest["included_files"] == 0

    def test_all_lockfiles_keeps_entries(self, tmp_path: Path):
        """Even if all files are omitted, manifest still records them."""
        diff_file = tmp_path / "pr.diff"
        diff_file.write_text(
            _hunk("package-lock.json", "x") +
            _hunk("yarn.lock", "y")
        )
        out = tmp_path / "bundle"
        manifest = build_context(diff_file, out)

        assert manifest["total_files"] == 2
        assert manifest["included_files"] == 0
        assert manifest["omitted_files"] == 2
        assert all(f["omitted"] for f in manifest["files"])


class TestBuildSummary:
    def test_summary_format(self):
        manifest = {
            "total_files": 3,
            "included_files": 2,
            "omitted_files": 1,
            "stack": "Languages: Python",
            "files": [
                {"path": "a.py", "status": "modified", "diff_lines": 10,
                 "diff_bytes": 200, "omitted": False, "diff_file": "diffs/a.py.diff"},
                {"path": "b.py", "status": "added", "diff_lines": 5,
                 "diff_bytes": 100, "omitted": False, "diff_file": "diffs/b.py.diff"},
                {"path": "c.lock", "status": "modified", "diff_lines": 500,
                 "diff_bytes": 10000, "omitted": True, "omit_reason": "lockfile_or_generated"},
            ],
        }
        summary = _build_summary(manifest, {})
        assert "3 files changed" in summary
        assert "2 included" in summary
        assert "1 omitted" in summary
        assert "~ a.py (10 lines)" in summary
        assert "+ b.py (5 lines)" in summary
        assert "c.lock [OMITTED:" in summary
