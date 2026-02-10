from pathlib import Path


def test_release_workflow_deletes_local_v2_tag_before_landfall() -> None:
    release_workflow = (
        Path(__file__).parent.parent / ".github" / "workflows" / "release.yml"
    )
    text = release_workflow.read_text(encoding="utf-8")

    landfall = text.find("- name: Run Landfall")
    assert landfall != -1, "expected release workflow to run Landfall"

    scrub_v2 = text.find("git tag -d v2")
    assert scrub_v2 != -1, "expected release workflow to delete local v2 tag"

    assert scrub_v2 < landfall, "v2 tag scrub must run before Landfall"

