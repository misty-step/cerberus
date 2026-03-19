"""Deploy infrastructure contract tests.

Validates declarative deployment config, CI/CD workflow, and secrets
documentation satisfy the infrastructure-as-code acceptance criteria.

Uses parsed TOML/YAML structures instead of substring matching to prevent
false positives from comments or unrelated content.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
ELIXIR_ROOT = REPO_ROOT / "cerberus-elixir"


class TestFlyToml:
    """fly.toml must define health check, port, and region via parsed TOML."""

    def setup_method(self) -> None:
        path = ELIXIR_ROOT / "fly.toml"
        assert path.exists(), "cerberus-elixir/fly.toml must exist"
        self.config = tomllib.loads(path.read_text(encoding="utf-8"))

    def test_defines_app_name(self) -> None:
        assert self.config.get("app"), "app name must be set"

    def test_defines_primary_region(self) -> None:
        assert self.config.get("primary_region"), "primary_region must be set"

    def test_env_port_matches_internal_port(self) -> None:
        env_port = self.config.get("env", {}).get("PORT")
        assert env_port is not None, "env.PORT must be defined in fly.toml"
        svc_port = self.config.get("http_service", {}).get("internal_port")
        assert svc_port is not None, "http_service.internal_port must be defined"
        assert int(env_port) == svc_port, (
            f"env.PORT ({env_port}) must match http_service.internal_port ({svc_port})"
        )

    def test_health_check_is_array_of_tables(self) -> None:
        checks = self.config["http_service"]["checks"]
        assert isinstance(checks, list), (
            "http_service.checks must be [[array of tables]], not nested table"
        )
        assert len(checks) >= 1

    def test_health_check_targets_api_health(self) -> None:
        checks = self.config["http_service"]["checks"]
        paths = [c.get("path") for c in checks]
        assert "/api/health" in paths

    def test_health_check_has_required_fields(self) -> None:
        check = self.config["http_service"]["checks"][0]
        for field in ("interval", "timeout", "grace_period", "method", "path"):
            assert field in check, f"health check missing required field: {field}"


class TestDeployWorkflow:
    """Deploy workflow must auto-deploy on merge, health-check, and checkpoint."""

    def setup_method(self) -> None:
        path = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
        assert path.exists(), ".github/workflows/deploy.yml must exist"
        self.text = path.read_text(encoding="utf-8")
        self.config = yaml.safe_load(self.text)

    def test_triggers_on_push_to_master(self) -> None:
        trigger = self.config.get("on") or self.config.get(True, {})
        push = trigger.get("push", {}) if isinstance(trigger, dict) else {}
        branches = push.get("branches", [])
        assert "master" in branches

    def test_triggers_on_relevant_paths(self) -> None:
        trigger = self.config.get("on") or self.config.get(True, {})
        push = trigger.get("push", {}) if isinstance(trigger, dict) else {}
        paths = push.get("paths", [])
        assert any("cerberus-elixir" in p for p in paths)
        assert any("defaults" in p for p in paths)

    def test_has_deploy_job(self) -> None:
        assert "deploy" in self.config.get("jobs", {})

    def test_permissions_grant_contents_read(self) -> None:
        perms = self.config.get("permissions", {})
        assert perms.get("contents") == "read", (
            "permissions must grant contents: read for private repo checkout"
        )
        assert set(perms.keys()) == {"contents"}, (
            f"permissions must be least-privilege; unexpected scopes: "
            f"{set(perms.keys()) - {'contents'}}"
        )

    def test_sprite_install_is_pinned_with_checksum(self) -> None:
        assert "install | sh" not in self.text
        assert "${SPRITE_VERSION}" in self.text
        assert "sha256sum -c" in self.text
        assert re.search(r"SPRITE_SHA256:\s*[0-9a-f]{64}", self.text)

    def test_deploy_authenticates(self) -> None:
        assert "SPRITE_TOKEN" in self.text

    def test_deploy_runs_health_check(self) -> None:
        assert "/api/health" in self.text

    def test_deploy_creates_checkpoint_on_success(self) -> None:
        assert "checkpoint create" in self.text

    def test_checkpoint_step_has_success_condition(self) -> None:
        steps = self.config["jobs"]["deploy"]["steps"]
        checkpoint_steps = [
            s for s in steps
            if isinstance(s.get("run", ""), str) and "checkpoint" in s.get("run", "")
        ]
        assert checkpoint_steps, "checkpoint step must exist"
        for step in checkpoint_steps:
            assert step.get("if") and "success()" in step["if"], (
                "checkpoint step must have if: success() condition"
            )


class TestSecretsDocumentation:
    """Required env vars must be documented."""

    def setup_method(self) -> None:
        readme = ELIXIR_ROOT / "README.md"
        assert readme.exists()
        self.text = readme.read_text(encoding="utf-8")

    def test_documents_api_key(self) -> None:
        assert "CERBERUS_API_KEY" in self.text

    def test_documents_openrouter_key(self) -> None:
        assert "CERBERUS_OPENROUTER_API_KEY" in self.text

    def test_documents_sprite_token(self) -> None:
        assert "SPRITE_TOKEN" in self.text

    def test_documents_db_path(self) -> None:
        assert "CERBERUS_DB_PATH" in self.text

    def test_documents_port(self) -> None:
        assert "PORT" in self.text


class TestDeployScriptRestart:
    """deploy-sprite.sh restart must avoid self-match and verify termination."""

    def setup_method(self) -> None:
        path = ELIXIR_ROOT / "deploy-sprite.sh"
        assert path.exists(), "cerberus-elixir/deploy-sprite.sh must exist"
        self.text = path.read_text(encoding="utf-8")
        match = re.search(r"^restart_app\(\)", self.text, re.MULTILINE)
        assert match, "restart_app() function must exist"
        start = match.start()
        body_start = self.text.index("\n", start) + 1
        next_fn = re.search(r"^\w+\(\)", self.text[body_start:], re.MULTILINE)
        end = body_start + next_fn.start() if next_fn else len(self.text)
        self.restart_body = self.text[start:end]

    def test_pkill_uses_self_exclusion_pattern(self) -> None:
        assert "[m]ix" in self.restart_body, (
            "pkill pattern must use [m]ix bracket trick to prevent self-match"
        )

    def test_no_bare_pkill_mix_run(self) -> None:
        assert 'pkill -f "mix run"' not in self.restart_body

    def test_polls_for_termination(self) -> None:
        assert "pgrep" in self.restart_body, (
            "restart must poll for process termination with pgrep"
        )

    def test_no_fixed_sleep_for_termination(self) -> None:
        assert "sleep 2" not in self.restart_body

    def test_escalates_to_sigkill(self) -> None:
        assert "pkill -9" in self.restart_body

    def test_nohup_obfuscates_pattern(self) -> None:
        nohup_start = self.restart_body.index("nohup")
        nohup_line = self.restart_body[nohup_start : self.restart_body.index("\n", nohup_start)]
        assert "mix run" not in nohup_line, (
            "nohup command must obfuscate 'mix run' (e.g. via variable) "
            "to prevent pkill matching the parent sh -c process"
        )
