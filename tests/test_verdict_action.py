import re
from pathlib import Path


def test_override_query_uses_rest_user_login() -> None:
    action_file = Path(__file__).parent.parent / "verdict" / "action.yml"
    content = action_file.read_text()

    assert re.search(r"actor:\s*\.user\.login", content)
