"""Deploy infrastructure contract tests for issue #414.

Validates that declarative deployment config, CI/CD workflow, and secrets
documentation exist and satisfy the infrastructure-as-code acceptance criteria.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
ELIXIR_ROOT = REPO_ROOT / "cerberus-elixir"


class TestFlyToml:
    """fly.toml must define health check, port, and region."""

    def setup_method(self) -> None:
        path = ELIXIR_ROOT / "fly.toml"
        assert path.exists(), "cerberus-elixir/fly.toml must exist"
        self.text = path.read_text(encoding="utf-8")

    def test_defines_app_name(self) -> None:
        assert "app" in self.text

    def test_defines_port_8080(self) -> None:
        assert "8080" in self.text

    def test_defines_health_check(self) -> None:
        assert "/api/health" in self.text

    def test_defines_region(self) -> None:
        # Must declare a primary region
        assert "primary_region" in self.text


class TestDeployWorkflow:
    """Deploy workflow must auto-deploy on merge, health-check, and checkpoint."""

    def setup_method(self) -> None:
        path = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
        assert path.exists(), ".github/workflows/deploy.yml must exist"
        self.text = path.read_text(encoding="utf-8")
        self.config = yaml.safe_load(self.text)

    def test_triggers_on_push_to_master(self) -> None:
        # YAML parses `on:` as boolean True key; check both
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
        jobs = self.config.get("jobs", {})
        assert "deploy" in jobs

    def test_deploy_installs_sprite_cli(self) -> None:
        assert "sprite" in self.text

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

    def test_checkpoint_only_on_success(self) -> None:
        # The checkpoint step must be conditional on prior success
        assert "success()" in self.text


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
        # Extract restart_app function body up to next top-level function or EOF
        match = re.search(r"^restart_app\(\)", self.text, re.MULTILINE)
        assert match, "restart_app() function must exist"
        start = match.start()
        body_start = self.text.index("\n", start) + 1
        next_fn = re.search(r"^\w+\(\)", self.text[body_start:], re.MULTILINE)
        end = body_start + next_fn.start() if next_fn else len(self.text)
        self.restart_body = self.text[start:end]

    def test_pkill_uses_self_exclusion_pattern(self) -> None:
        """pkill must use bracket trick to avoid matching its own process."""
        assert "[m]ix" in self.restart_body, (
            "pkill pattern must use [m]ix bracket trick to prevent self-match"
        )

    def test_no_bare_pkill_mix_run(self) -> None:
        """Must not use bare 'pkill -f "mix run"' (matches own sh -c)."""
        assert 'pkill -f "mix run"' not in self.restart_body

    def test_polls_for_termination(self) -> None:
        """Must poll with pgrep instead of fixed sleep."""
        assert "pgrep" in self.restart_body, (
            "restart must poll for process termination with pgrep"
        )

    def test_no_fixed_sleep_for_termination(self) -> None:
        """Must not rely on fixed 'sleep 2' for termination wait."""
        # Allow sleep inside a polling loop but not as standalone termination wait
        assert "sleep 2" not in self.restart_body

    def test_escalates_to_sigkill(self) -> None:
        """Must SIGKILL if graceful shutdown fails after polling."""
        assert "pkill -9" in self.restart_body

    def test_nohup_obfuscates_pattern(self) -> None:
        """nohup line must not contain literal 'mix run' to prevent parent sh -c match."""
        # The outer sh -c command line is visible to pkill -f; if the nohup
        # line contains 'mix run --no-halt' literally, pkill kills the parent
        nohup_start = self.restart_body.index("nohup")
        nohup_line = self.restart_body[nohup_start : self.restart_body.index("\n", nohup_start)]
        assert "mix run" not in nohup_line, (
            "nohup command must obfuscate 'mix run' (e.g. via variable) "
            "to prevent pkill matching the parent sh -c process"
        )
