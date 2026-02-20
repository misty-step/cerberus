import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
READ_DEFAULTS = ROOT / "scripts" / "read-defaults-config.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(READ_DEFAULTS), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_simple_yaml_config_parsed(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text(
        "\n".join(
            [
                "version: 1",
                "model:",
                '  default: \"openrouter/default\"',
                "  pool:",
                "    - openrouter/a",
                "    - openrouter/b",
                "reviewers:",
                "  - name: SENTINEL",
                "    perspective: security",
                '    model: \"openrouter/specific\"',
                '    description: \"Security\"',
                "",
            ]
        )
    )

    meta = _run(
        "reviewer-meta",
        "--config",
        str(config),
        "--perspective",
        "security",
    )
    assert meta.returncode == 0, meta.stderr
    assert meta.stdout.strip() == "SENTINEL\topenrouter/specific\tSecurity"

    default = _run("model-default", "--config", str(config))
    assert default.returncode == 0, default.stderr
    assert default.stdout.strip() == "openrouter/default"

    pool = _run("model-pool", "--config", str(config))
    assert pool.returncode == 0, pool.stderr
    assert pool.stdout.strip().splitlines() == ["openrouter/a", "openrouter/b"]


def test_complex_yaml_features_parsed(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text(
        "\n".join(
            [
                "# comment: with colon",
                "notes: |",
                "  multiline: value",
                "  still fine",
                "model:",
                '  default: &def_model \"openrouter/anchored\"',
                "  pool:",
                "    - openrouter/a",
                "reviewers:",
                "  - name: APOLLO",
                "    perspective: correctness",
                "    model: *def_model",
                '    description: \"Correctness\"',
                "",
            ]
        )
    )

    meta = _run(
        "reviewer-meta",
        "--config",
        str(config),
        "--perspective",
        "correctness",
    )
    assert meta.returncode == 0, meta.stderr
    assert meta.stdout.strip() == "APOLLO\topenrouter/anchored\tCorrectness"


def test_missing_required_field_errors_clearly(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text(
        "\n".join(
            [
                "reviewers:",
                "  - name: SENTINEL",
                '    model: \"openrouter/x\"',
                "",
            ]
        )
    )

    result = _run(
        "reviewer-meta",
        "--config",
        str(config),
        "--perspective",
        "security",
    )
    assert result.returncode == 2
    assert "config.reviewers[0].perspective" in result.stderr


def test_invalid_yaml_errors_clearly(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text("reviewers: [\n")

    result = _run("model-default", "--config", str(config))
    assert result.returncode == 2
    assert "invalid YAML" in result.stderr

