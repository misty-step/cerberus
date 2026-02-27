from pathlib import Path

ROOT = Path(__file__).parent.parent
MINIMAL_TEMPLATE = ROOT / "templates" / "consumer-workflow-minimal.yml"


def _read() -> str:
    return MINIMAL_TEMPLATE.read_text()


def test_minimal_template_uses_preflight_action() -> None:
    content = _read()

    assert "preflight:" in content
    assert "uses: misty-step/cerberus/preflight@master" in content
    assert "should_run" in content
    assert "skip_reason" in content


def test_minimal_template_wires_api_key_to_preflight() -> None:
    content = _read()

    assert "api-key:" in content


def test_minimal_template_removes_draft_check_job() -> None:
    content = _read()

    assert "draft-check:" not in content
    assert "uses: misty-step/cerberus/draft-check@master" not in content
    assert "is_draft" not in content


def test_minimal_template_removes_bespoke_fork_guard() -> None:
    content = _read()

    assert "head.repo.full_name == github.repository" not in content


def test_minimal_template_gates_on_should_run() -> None:
    content = _read()

    assert "needs.preflight.outputs.should_run == 'true'" in content
    assert "needs.draft-check.outputs.is_draft" not in content
