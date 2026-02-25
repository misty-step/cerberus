"""Tests for model selection and tiered pool behavior in run-reviewer."""

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def write_stub_pi(path: Path) -> None:
    make_executable(
        path,
        (
            "#!/usr/bin/env bash\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Stub output",'
            '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
            '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )


def write_simple_diff(path: Path) -> None:
    path.write_text("diff --git a/app.py b/app.py\n+print('hello')\n")


def write_fake_cerberus_root(root: Path, *, config_yml: str, perspective: str = "security") -> None:
    (root / "defaults").mkdir(parents=True)
    (root / "templates").mkdir(parents=True)
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / ".opencode" / "agents").mkdir(parents=True)

    (root / "defaults" / "config.yml").write_text(config_yml)
    (root / "templates" / "review-prompt.md").write_text("{{DIFF_FILE}}\n{{PERSPECTIVE}}\n")

    for rel in (
        "scripts/read-defaults-config.py",
        "scripts/render-review-prompt.py",
        "scripts/lib/__init__.py",
        "scripts/lib/defaults_config.py",
        "scripts/lib/review_prompt.py",
        "scripts/lib/prompt_sanitize.py",
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text((REPO_ROOT / rel).read_text())

    (root / ".opencode" / "agents" / f"{perspective}.md").write_text("AGENT BODY\n")


def make_env(
    bin_dir: Path,
    diff_file: Path,
    cerberus_root: Path,
    artifacts_dir: Path,
) -> dict[str, str]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(cerberus_root)
    env["CERBERUS_TMP"] = str(artifacts_dir)
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "5"
    env["CERBERUS_TEST_NO_SLEEP"] = "1"
    env["CERBERUS_ALLOW_MISSING_REVIEWER_PROFILES"] = "1"
    return env


def artifact(artifacts_dir: Path, name: str) -> Path:
    return artifacts_dir / f"security-{name}"


class TestModelPoolSelection:
    def _run(
        self,
        tmp_path: Path,
        config: str,
        env_extra: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_pi(bin_dir / "pi")

        cerberus_root = tmp_path / "cerberus-root"
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        artifacts_dir = tmp_path / "artifacts"
        env = make_env(bin_dir, diff_file, cerberus_root, artifacts_dir)
        if env_extra:
            env.update(env_extra)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result, artifacts_dir

    def test_requested_tier_pool_is_used(self, tmp_path: Path) -> None:
        config = '''
version: 1
model:
  default: "openrouter/default"
  pool:
    - "openrouter/legacy-a"
    - "openrouter/legacy-b"
  tiers:
    flash:
      - "openrouter/flash-a"
      - "openrouter/flash-b"
    standard:
      - "openrouter/standard-a"
reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        result, artifacts_dir = self._run(tmp_path, config, {"MODEL_TIER": "flash"})
        assert result.returncode == 0
        model = artifact(artifacts_dir, "primary-model").read_text().strip()
        assert model in {"openrouter/flash-a", "openrouter/flash-b"}

    def test_missing_requested_tier_falls_back_to_standard(self, tmp_path: Path) -> None:
        config = '''
version: 1
model:
  default: "openrouter/default"
  pool:
    - "openrouter/legacy-a"
  tiers:
    standard:
      - "openrouter/standard-a"
      - "openrouter/standard-b"
reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        result, artifacts_dir = self._run(tmp_path, config, {"MODEL_TIER": "pro"})
        assert result.returncode == 0
        model = artifact(artifacts_dir, "primary-model").read_text().strip()
        assert model in {"openrouter/standard-a", "openrouter/standard-b"}

    def test_missing_requested_and_standard_falls_back_to_unscoped_pool(self, tmp_path: Path) -> None:
        config = '''
version: 1
model:
  default: "openrouter/default"
  pool:
    - "openrouter/legacy-a"
    - "openrouter/legacy-b"
  tiers:
    flash:
      - "openrouter/flash-a"
reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        result, artifacts_dir = self._run(tmp_path, config, {"MODEL_TIER": "pro"})
        assert result.returncode == 0
        model = artifact(artifacts_dir, "primary-model").read_text().strip()
        assert model in {"openrouter/legacy-a", "openrouter/legacy-b"}

    def test_pool_with_no_models_falls_back_to_default(self, tmp_path: Path) -> None:
        config = '''
version: 1
model:
  default: "openrouter/default"
reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        result, artifacts_dir = self._run(tmp_path, config)
        assert result.returncode == 0
        configured = artifact(artifacts_dir, "configured-model").read_text().strip()
        primary = artifact(artifacts_dir, "primary-model").read_text().strip()
        assert configured == "openrouter/default"
        assert primary == "openrouter/default"

    def test_case_insensitive_tier_input(self, tmp_path: Path) -> None:
        config = '''
version: 1
model:
  default: "openrouter/default"
  tiers:
    flash:
      - "openrouter/flash-a"
reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        result, artifacts_dir = self._run(tmp_path, config, {"MODEL_TIER": "FlAsH"})
        assert result.returncode == 0
        model = artifact(artifacts_dir, "primary-model").read_text().strip()
        assert model == "openrouter/flash-a"


class TestModelPrecedence:
    def _run(
        self,
        tmp_path: Path,
        config: str,
        env_extra: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_pi(bin_dir / "pi")

        cerberus_root = tmp_path / "cerberus-root"
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        artifacts_dir = tmp_path / "artifacts"
        env = make_env(bin_dir, diff_file, cerberus_root, artifacts_dir)
        if env_extra:
            env.update(env_extra)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result, artifacts_dir

    def test_reviewer_model_overrides_default_model(self, tmp_path: Path) -> None:
        config = '''
version: 1
model:
  default: "openrouter/default"
reviewers:
  - name: SENTINEL
    perspective: security
    model: "openrouter/reviewer-model"
'''
        result, artifacts_dir = self._run(tmp_path, config)
        assert result.returncode == 0
        assert artifact(artifacts_dir, "configured-model").read_text().strip() == "openrouter/reviewer-model"
        assert artifact(artifacts_dir, "primary-model").read_text().strip() == "openrouter/reviewer-model"

    def test_input_model_override_has_highest_precedence(self, tmp_path: Path) -> None:
        config = '''
version: 1
model:
  default: "openrouter/default"
reviewers:
  - name: SENTINEL
    perspective: security
    model: "openrouter/reviewer-model"
'''
        result, artifacts_dir = self._run(tmp_path, config, {"OPENCODE_MODEL": "openrouter/input-model"})
        assert result.returncode == 0
        assert artifact(artifacts_dir, "configured-model").read_text().strip() == "openrouter/reviewer-model"
        assert artifact(artifacts_dir, "primary-model").read_text().strip() == "openrouter/input-model"

    def test_default_model_used_when_reviewer_model_missing(self, tmp_path: Path) -> None:
        config = '''
version: 1
model:
  default: "openrouter/default-model"
reviewers:
  - name: SENTINEL
    perspective: security
'''
        result, artifacts_dir = self._run(tmp_path, config)
        assert result.returncode == 0
        assert artifact(artifacts_dir, "configured-model").read_text().strip() == "openrouter/default-model"
        assert artifact(artifacts_dir, "primary-model").read_text().strip() == "openrouter/default-model"
