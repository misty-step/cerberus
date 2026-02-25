"""Tests for lib.runtime_facade."""

from pathlib import Path

from lib.runtime_facade import (
    RuntimeAttemptRequest,
    build_pi_command,
    classify_runtime_error,
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
