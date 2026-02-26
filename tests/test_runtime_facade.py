"""Tests for lib.runtime_facade."""

import subprocess
from pathlib import Path

from lib.runtime_facade import (
    RuntimeAttemptRequest,
    build_pi_command,
    classify_runtime_error,
    provider_api_key_env_var,
    run_pi_attempt,
)


def make_request(tmp_path: Path, *, model: str = "openrouter/moonshotai/kimi-k2.5") -> RuntimeAttemptRequest:
    return RuntimeAttemptRequest(
        perspective="security",
        provider="openrouter",
        model=model,
        prompt_file=tmp_path / "prompt.md",
        system_prompt_file=tmp_path / "system.md",
        timeout_seconds=30,
        tools=["read", "grep", "find", "ls", "write", "bash"],
        extensions=["pi/extensions/reviewer-guard.ts"],
        skills=["pi/skills/base/SKILL.md"],
        thinking_level="high",
        api_key="test-key",
        agent_dir=tmp_path / "pi-agent",
        isolated_home=tmp_path / "home",
    )


class TestBuildPiCommand:
    def test_strips_provider_prefix_for_model(self, tmp_path: Path) -> None:
        req = make_request(tmp_path, model="openrouter/moonshotai/kimi-k2.5")
        cmd = build_pi_command(req)
        model_index = cmd.index("--model") + 1
        assert cmd[model_index] == "moonshotai/kimi-k2.5"

    def test_keeps_unprefixed_model(self, tmp_path: Path) -> None:
        req = make_request(tmp_path, model="z-ai/glm-5")
        cmd = build_pi_command(req)
        model_index = cmd.index("--model") + 1
        assert cmd[model_index] == "z-ai/glm-5"

    def test_includes_explicit_extensions_and_skills(self, tmp_path: Path) -> None:
        req = make_request(tmp_path)
        cmd = build_pi_command(req)
        assert "--no-extensions" in cmd
        assert "--extension" in cmd
        assert "pi/extensions/reviewer-guard.ts" in cmd
        assert "--no-skills" in cmd
        assert "--skill" in cmd
        assert "pi/skills/base/SKILL.md" in cmd
        assert "--print" in cmd

    def test_does_not_pass_api_key_in_cli_args(self, tmp_path: Path) -> None:
        req = make_request(tmp_path)
        cmd = build_pi_command(req)
        assert "--api-key" not in cmd


class TestProviderApiKeyEnvVar:
    def test_known_provider_uses_specific_env_var(self) -> None:
        assert provider_api_key_env_var("openai") == "OPENAI_API_KEY"

    def test_unknown_provider_falls_back_to_openrouter(self) -> None:
        assert provider_api_key_env_var("unknown-provider") == "OPENROUTER_API_KEY"


class TestClassifyRuntimeError:
    def test_success(self) -> None:
        t, c, r = classify_runtime_error(stdout="ok", stderr="", exit_code=0)
        assert (t, c, r) == ("none", "none", None)

    def test_timeout(self) -> None:
        t, c, r = classify_runtime_error(stdout="", stderr="", exit_code=124)
        assert (t, c, r) == ("timeout", "timeout", None)

    def test_auth_or_quota(self) -> None:
        t, c, _ = classify_runtime_error(
            stdout="",
            stderr="HTTP 401 unauthorized incorrect_api_key",
            exit_code=1,
        )
        assert (t, c) == ("permanent", "auth_or_quota")

    def test_rate_limit_with_retry_after(self) -> None:
        t, c, r = classify_runtime_error(
            stdout="",
            stderr='HTTP 429 Too Many Requests Retry-After: 9',
            exit_code=1,
        )
        assert (t, c, r) == ("transient", "rate_limit", 9)

    def test_server_5xx(self) -> None:
        t, c, _ = classify_runtime_error(
            stdout="",
            stderr="HTTP 503 service unavailable",
            exit_code=1,
        )
        assert (t, c) == ("transient", "server_5xx")

    def test_network(self) -> None:
        t, c, _ = classify_runtime_error(
            stdout="",
            stderr="network timeout while connecting",
            exit_code=1,
        )
        assert (t, c) == ("transient", "network")

    def test_client_4xx(self) -> None:
        t, c, _ = classify_runtime_error(
            stdout="",
            stderr="HTTP 404 model not found",
            exit_code=1,
        )
        assert (t, c) == ("permanent", "client_4xx")

    def test_rate_limit_without_retry_after(self) -> None:
        t, c, r = classify_runtime_error(
            stdout="",
            stderr="HTTP 429 Too Many Requests",
            exit_code=1,
        )
        assert (t, c, r) == ("transient", "rate_limit", None)

    def test_provider_generic(self) -> None:
        t, c, r = classify_runtime_error(
            stdout="",
            stderr="provider returned error",
            exit_code=1,
        )
        assert (t, c, r) == ("transient", "provider_generic", None)

    def test_unknown_error_classification(self) -> None:
        t, c, r = classify_runtime_error(
            stdout="",
            stderr="totally unexpected failure",
            exit_code=42,
        )
        assert (t, c, r) == ("unknown", "unknown", None)


class TestRunPiAttempt:
    def test_prompt_read_error_is_reported(self, tmp_path: Path) -> None:
        req = make_request(tmp_path)
        # Intentionally do not create req.prompt_file.
        result = run_pi_attempt(req)

        assert result.exit_code == 1
        assert result.timed_out is False
        assert "unable to read prompt file" in result.stderr

    def test_optional_env_fields_are_forwarded(self, monkeypatch, tmp_path: Path) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("hello")

        trusted = tmp_path / "trusted.md"
        telemetry = tmp_path / "telemetry.ndjson"

        captured_env: dict[str, str] = {}

        class Proc:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake_run(cmd, input, capture_output, text, timeout, env):
            captured_env.update(env)
            return Proc()

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        monkeypatch.setenv("LC_ALL", "C.UTF-8")

        req = RuntimeAttemptRequest(
            perspective="security",
            provider="openrouter",
            model="openrouter/moonshotai/kimi-k2.5",
            prompt_file=prompt_file,
            system_prompt_file=tmp_path / "system.md",
            timeout_seconds=30,
            tools=["read", "grep"],
            extensions=[],
            skills=[],
            thinking_level=None,
            api_key="test-key",
            agent_dir=tmp_path / "pi-agent",
            isolated_home=tmp_path / "home",
            max_steps=7,
            trusted_system_prompt_file=trusted,
            telemetry_file=telemetry,
            prompt_capture_path="/tmp/capture.md",
        )

        result = run_pi_attempt(req)
        assert result.exit_code == 0
        assert captured_env["LANG"] == "en_US.UTF-8"
        assert captured_env["LC_ALL"] == "C.UTF-8"
        assert captured_env["CERBERUS_MAX_STEPS"] == "7"
        assert captured_env["CERBERUS_TRUSTED_SYSTEM_PROMPT_FILE"] == str(trusted)
        assert captured_env["CERBERUS_RUNTIME_TELEMETRY_FILE"] == str(telemetry)
        assert captured_env["CERBERUS_PROMPT_CAPTURE_PATH"] == "/tmp/capture.md"
        assert captured_env["OPENROUTER_API_KEY"] == "test-key"
        assert captured_env["CERBERUS_OPENROUTER_API_KEY"] == "test-key"

    def test_provider_specific_api_key_env_is_used(self, monkeypatch, tmp_path: Path) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("hello")

        captured_env: dict[str, str] = {}

        class Proc:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake_run(cmd, input, capture_output, text, timeout, env):
            captured_env.update(env)
            return Proc()

        monkeypatch.setattr(subprocess, "run", fake_run)

        req = RuntimeAttemptRequest(
            perspective="security",
            provider="openai",
            model="openai/gpt-5",
            prompt_file=prompt_file,
            system_prompt_file=tmp_path / "system.md",
            timeout_seconds=30,
            tools=["read"],
            extensions=[],
            skills=[],
            thinking_level=None,
            api_key="test-key",
            agent_dir=tmp_path / "pi-agent",
            isolated_home=tmp_path / "home",
        )

        result = run_pi_attempt(req)
        assert result.exit_code == 0
        assert captured_env["OPENAI_API_KEY"] == "test-key"
        assert "CERBERUS_OPENROUTER_API_KEY" not in captured_env

    def test_spawn_failure_returns_structured_result(self, monkeypatch, tmp_path: Path) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("hello")

        def fake_run(*args, **kwargs):
            raise OSError("pi not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        req = RuntimeAttemptRequest(
            perspective="security",
            provider="openrouter",
            model="openrouter/moonshotai/kimi-k2.5",
            prompt_file=prompt_file,
            system_prompt_file=tmp_path / "system.md",
            timeout_seconds=30,
            tools=["read"],
            extensions=[],
            skills=[],
            thinking_level=None,
            api_key="test-key",
            agent_dir=tmp_path / "pi-agent",
            isolated_home=tmp_path / "home",
        )

        result = run_pi_attempt(req)
        assert result.exit_code == 1
        assert result.timed_out is False
        assert "unable to execute pi runtime" in result.stderr

    def test_timeout_decodes_bytes_output(self, monkeypatch, tmp_path: Path) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("hello")

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=["pi"],
                timeout=1,
                output=b"partial-bytes",
                stderr=b"error-bytes",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        req = RuntimeAttemptRequest(
            perspective="security",
            provider="openrouter",
            model="openrouter/moonshotai/kimi-k2.5",
            prompt_file=prompt_file,
            system_prompt_file=tmp_path / "system.md",
            timeout_seconds=1,
            tools=["read"],
            extensions=[],
            skills=[],
            thinking_level=None,
            api_key="test-key",
            agent_dir=tmp_path / "pi-agent",
            isolated_home=tmp_path / "home",
        )

        result = run_pi_attempt(req)
        assert result.exit_code == 124
        assert result.timed_out is True
        assert result.stdout == "partial-bytes"
        assert result.stderr == "error-bytes"
