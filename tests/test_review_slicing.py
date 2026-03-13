from pathlib import Path

from lib.review_slicing import plan_review_slice


def test_plan_review_slice_applies_to_large_security_diff(tmp_path: Path) -> None:
    diff_file = tmp_path / "large.diff"
    diff_file.write_text(
        "\n".join(
            [
                "diff --git a/docs/notes.md b/docs/notes.md",
                "--- a/docs/notes.md",
                "+++ b/docs/notes.md",
                "@@ -1 +1,4 @@",
                *["+doc line" for _ in range(4)],
                "diff --git a/src/auth/session.py b/src/auth/session.py",
                "--- a/src/auth/session.py",
                "+++ b/src/auth/session.py",
                "@@ -1 +1,180 @@",
                *["+token = load_token()" for _ in range(180)],
                "diff --git a/.github/workflows/review.yml b/.github/workflows/review.yml",
                "--- a/.github/workflows/review.yml",
                "+++ b/.github/workflows/review.yml",
                "@@ -1 +1,140 @@",
                *["+permissions: write-all" for _ in range(140)],
                "diff --git a/tests/test_auth.py b/tests/test_auth.py",
                "--- a/tests/test_auth.py",
                "+++ b/tests/test_auth.py",
                "@@ -1 +1,80 @@",
                *["+assert True" for _ in range(80)],
                "",
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_review_slice(diff_file, perspective="security")

    assert plan.slice_applied is True
    assert plan.size_bucket == "large"
    assert plan.selected_files[0] in {"src/auth/session.py", ".github/workflows/review.yml"}
    assert "docs/notes.md" in plan.deprioritized_files
    assert "src/auth/session.py" in plan.slice_diff
    assert ".github/workflows/review.yml" in plan.slice_diff
    assert "docs/notes.md" not in plan.slice_diff


def test_plan_review_slice_skips_small_diff(tmp_path: Path) -> None:
    diff_file = tmp_path / "small.diff"
    diff_file.write_text(
        "\n".join(
            [
                "diff --git a/src/app.py b/src/app.py",
                "--- a/src/app.py",
                "+++ b/src/app.py",
                "@@ -1 +1,8 @@",
                *["+print('hello')" for _ in range(8)],
                "",
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_review_slice(diff_file, perspective="security")

    assert plan.slice_applied is False
    assert plan.size_bucket == "small"
    assert plan.selected_files == ["src/app.py"]
    assert plan.slice_diff == diff_file.read_text(encoding="utf-8")


def test_correctness_slice_prioritizes_runtime_and_logic_paths(tmp_path: Path) -> None:
    diff_file = tmp_path / "large.diff"
    diff_file.write_text(
        "\n".join(
            [
                "diff --git a/docs/notes.md b/docs/notes.md",
                "--- a/docs/notes.md",
                "+++ b/docs/notes.md",
                "@@ -1 +1,40 @@",
                *["+doc line" for _ in range(40)],
                "diff --git a/src/runtime/router.py b/src/runtime/router.py",
                "--- a/src/runtime/router.py",
                "+++ b/src/runtime/router.py",
                "@@ -1 +1,190 @@",
                *["+route = compute_route()" for _ in range(190)],
                "diff --git a/src/payments/calc.py b/src/payments/calc.py",
                "--- a/src/payments/calc.py",
                "+++ b/src/payments/calc.py",
                "@@ -1 +1,170 @@",
                *["+total = subtotal + tax" for _ in range(170)],
                "",
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_review_slice(diff_file, perspective="correctness")

    assert plan.slice_applied is True
    assert plan.selected_files[:2] == ["src/runtime/router.py", "src/payments/calc.py"]
    assert "docs/notes.md" not in plan.slice_diff


def test_volume_401_replay_slice_prioritizes_date_and_error_paths(tmp_path: Path) -> None:
    diff_file = tmp_path / "volume-401-large.diff"
    diff_file.write_text(
        "\n".join(
            [
                "diff --git a/docs/notes.md b/docs/notes.md",
                "--- a/docs/notes.md",
                "+++ b/docs/notes.md",
                "@@ -1 +1,40 @@",
                *["+doc line" for _ in range(40)],
                "diff --git a/src/reporting/date_window.py b/src/reporting/date_window.py",
                "--- a/src/reporting/date_window.py",
                "+++ b/src/reporting/date_window.py",
                "@@ -1 +1,190 @@",
                *["+window_end = start + offset" for _ in range(190)],
                "diff --git a/src/api/error_response.py b/src/api/error_response.py",
                "--- a/src/api/error_response.py",
                "+++ b/src/api/error_response.py",
                "@@ -1 +1,170 @@",
                *["+return {'error': str(exc)}" for _ in range(170)],
                "",
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_review_slice(diff_file, perspective="correctness")

    assert plan.slice_applied is True
    assert plan.selected_files == ["src/reporting/date_window.py", "src/api/error_response.py"]
    assert "docs/notes.md" in plan.deprioritized_files
