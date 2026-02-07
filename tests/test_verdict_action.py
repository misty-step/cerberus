import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
VERDICT_ACTION_FILE = ROOT / "verdict" / "action.yml"
POST_COMMENT_SCRIPT = ROOT / "scripts" / "post-comment.sh"


def test_override_query_uses_rest_user_login() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert re.search(r"actor:\s*\.user\.login", content)


def test_verdict_action_updates_comment_with_typed_file_field() -> None:
    content = VERDICT_ACTION_FILE.read_text()

    assert "-X PATCH -F body=@/tmp/council-comment.md" in content
    assert "-X PATCH -f body=\"$(cat /tmp/council-comment.md)\"" not in content


def test_post_comment_updates_comment_with_typed_file_field() -> None:
    content = POST_COMMENT_SCRIPT.read_text()

    assert "-X PATCH -F body=@\"$comment_file\"" in content
    assert "-X PATCH -f body=\"$(cat \"$comment_file\")\"" not in content
