from lib.diff_positions import build_newline_to_position


def test_single_hunk_maps_context_and_additions() -> None:
    patch = "\n".join(
        [
            "@@ -1,3 +1,4 @@",
            " line1",
            "-line2",
            "+line2b",
            " line3",
            "+line4",
        ]
    )
    mapping = build_newline_to_position(patch)

    # positions are 1-indexed in the patch text
    # 1: @@ ... @@  (no mapping)
    # 2:  line1     -> new line 1
    # 3: -line2     (no new line)
    # 4: +line2b    -> new line 2
    # 5:  line3     -> new line 3
    # 6: +line4     -> new line 4
    assert mapping[1] == 2
    assert mapping[2] == 4
    assert mapping[3] == 5
    assert mapping[4] == 6


def test_multiple_hunks_reset_new_line_counter() -> None:
    patch = "\n".join(
        [
            "@@ -1,2 +1,2 @@",
            " a",
            "+b",
            "@@ -10 +20 @@",
            " c",
        ]
    )
    mapping = build_newline_to_position(patch)

    assert mapping[1] == 2
    assert mapping[2] == 3
    assert mapping[20] == 5


def test_deletions_do_not_advance_new_line() -> None:
    patch = "\n".join(
        [
            "@@ -5,3 +5,2 @@",
            "-gone1",
            "-gone2",
            " keep1",
            " keep2",
        ]
    )
    mapping = build_newline_to_position(patch)

    assert mapping[5] == 4
    assert mapping[6] == 5


def test_empty_lines_in_patch_skipped() -> None:
    patch = "@@ -1,2 +1,2 @@\n line1\n\n line2\n"
    mapping = build_newline_to_position(patch)
    assert mapping[1] == 2   # " line1"
    assert mapping[2] == 4   # " line2" (empty line at position 3 skipped)


def test_no_newline_marker_skipped() -> None:
    patch = "@@ -1,2 +1,2 @@\n line1\n\\ No newline at end of file\n line2\n"
    mapping = build_newline_to_position(patch)
    assert mapping[1] == 2   # " line1"
    assert mapping[2] == 4   # " line2" (backslash marker at position 3 skipped)


def test_empty_patch_returns_empty() -> None:
    assert build_newline_to_position("") == {}


def test_none_patch_returns_empty() -> None:
    assert build_newline_to_position(None) == {}


def test_ignores_lines_before_first_hunk() -> None:
    patch = "\n".join(
        [
            "diff --git a/x b/x",
            "index 000..111 100644",
            "--- a/x",
            "+++ b/x",
            "@@ -1 +1 @@",
            "+hi",
        ]
    )
    mapping = build_newline_to_position(patch)
    assert mapping[1] == 6

