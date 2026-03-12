from pathlib import Path


ROOT = Path(__file__).parent.parent
MATRIX_ACTION_FILE = ROOT / "matrix" / "action.yml"


def test_matrix_action_passes_panel_input_to_generator_env() -> None:
    content = MATRIX_ACTION_FILE.read_text()

    assert "PANEL_FILTER: ${{ inputs.panel }}" in content
    assert 'MODEL_TIER="$INPUT_MODEL_TIER" REVIEW_WAVE="$INPUT_WAVE" \\' in content
    assert 'python3 "${{ github.action_path }}/generate-matrix.py" "$config_file"' in content


def test_matrix_action_no_longer_calls_filter_panel_script() -> None:
    content = MATRIX_ACTION_FILE.read_text()

    assert "filter-panel.py" not in content
