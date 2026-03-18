"""Deploy infrastructure contract tests for issue #414.

Validates that declarative deployment config, CI/CD workflow, and secrets
documentation exist and satisfy the infrastructure-as-code acceptance criteria.
"""

from __future__ import annotations

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
