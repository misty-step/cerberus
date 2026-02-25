import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "validate-inputs.sh"


def run_validator(env_extra: dict[str, str], github_env: Path) -> tuple[int, str, str, str]:
    env = os.environ.copy()
    env.pop("INPUT_API_KEY", None)
    env.pop("INPUT_KIMI_API_KEY", None)
    env.pop("CERBERUS_API_KEY", None)
    env.pop("CERBERUS_OPENROUTER_API_KEY", None)
    env.pop("OPENROUTER_API_KEY", None)
    env.update(env_extra)

    github_env.write_text("")
    env["GITHUB_ENV"] = str(github_env)

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr, github_env.read_text()


def test_prefers_explicit_input_key(tmp_path: Path) -> None:
    code, _out, _err, github_env = run_validator(
        {
            "INPUT_API_KEY": "input-key",
            "CERBERUS_API_KEY": "cerberus-key",
            "CERBERUS_OPENROUTER_API_KEY": "cerberus-openrouter-key",
            "OPENROUTER_API_KEY": "openrouter-key",
        },
        tmp_path / "github.env",
    )

    assert code == 0
    assert "OPENROUTER_API_KEY=input-key" in github_env


def test_uses_cerberus_env_fallback(tmp_path: Path) -> None:
    code, _out, _err, github_env = run_validator(
        {"CERBERUS_API_KEY": "cerberus-key"},
        tmp_path / "github.env",
    )

    assert code == 0
    assert "OPENROUTER_API_KEY=cerberus-key" in github_env


def test_uses_cerberus_openrouter_env_fallback(tmp_path: Path) -> None:
    code, _out, _err, github_env = run_validator(
        {"CERBERUS_OPENROUTER_API_KEY": "cerberus-openrouter-key"},
        tmp_path / "github.env",
    )

    assert code == 0
    assert "OPENROUTER_API_KEY=cerberus-openrouter-key" in github_env


def test_uses_openrouter_env_fallback(tmp_path: Path) -> None:
    code, _out, _err, github_env = run_validator(
        {"OPENROUTER_API_KEY": "openrouter-key"},
        tmp_path / "github.env",
    )

    assert code == 0
    assert "OPENROUTER_API_KEY=openrouter-key" in github_env


def test_fails_with_clear_message_when_no_key(tmp_path: Path) -> None:
    code, _out, err, _github_env = run_validator({}, tmp_path / "github.env")

    assert code != 0
    assert "Missing API key for Cerberus review" in err
    assert "CERBERUS_API_KEY" in err
    assert "CERBERUS_OPENROUTER_API_KEY" in err
    assert "OPENROUTER_API_KEY" in err


def test_accepts_deprecated_kimi_api_key_input(tmp_path: Path) -> None:
    code, out, err, github_env = run_validator(
        {"INPUT_KIMI_API_KEY": "deprecated-key"},
        tmp_path / "github.env",
    )

    assert code == 0
    assert "OPENROUTER_API_KEY=deprecated-key" in github_env
    assert "kimi-api-key" in (out + err)


def test_prefers_api_key_over_kimi_api_key(tmp_path: Path) -> None:
    code, _out, _err, github_env = run_validator(
        {"INPUT_API_KEY": "new-key", "INPUT_KIMI_API_KEY": "deprecated-key"},
        tmp_path / "github.env",
    )

    assert code == 0
    assert "OPENROUTER_API_KEY=new-key" in github_env
