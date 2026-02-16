from pathlib import Path


def test_license_has_no_unfilled_copyright_placeholders():
    license_text = Path("LICENSE").read_text(encoding="utf-8")

    assert "[yyyy]" not in license_text
    assert "[name of copyright owner]" not in license_text
