"""Tests for model pool random assignment feature (issue #148)."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def make_env(bin_dir: Path, diff_file: Path, cerberus_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(cerberus_root)
    env["CERBERUS_TMP"] = "/tmp"
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "5"
    return env


def write_stub_opencode(path: Path, verdict: str = "PASS") -> None:
    make_executable(
        path,
        (
            "#!/usr/bin/env bash\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"'
            + verdict
            + '","confidence":0.95,"summary":"Stub output",'
              '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
              '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )


def write_simple_diff(path: Path) -> None:
    path.write_text("diff --git a/app.py b/app.py\n+print('hello')\n")


def write_fake_cerberus_root(
    root: Path,
    *,
    config_yml: str,
    perspective: str = "security",
) -> None:
    (root / "defaults").mkdir(parents=True)
    (root / "templates").mkdir(parents=True)
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / ".opencode" / "agents").mkdir(parents=True)

    (root / "defaults" / "config.yml").write_text(config_yml)
    (root / "templates" / "review-prompt.md").write_text("{{DIFF_FILE}}\n{{PERSPECTIVE}}\n")
    (root / "scripts" / "read-defaults-config.py").write_text(
        (REPO_ROOT / "scripts" / "read-defaults-config.py").read_text()
    )
    (root / "scripts" / "render-review-prompt.py").write_text(
        (REPO_ROOT / "scripts" / "render-review-prompt.py").read_text()
    )
    (root / "scripts" / "lib" / "__init__.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "__init__.py").read_text()
    )
    (root / "scripts" / "lib" / "defaults_config.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "defaults_config.py").read_text()
    )
    (root / "scripts" / "lib" / "review_prompt.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "review_prompt.py").read_text()
    )
    (root / "scripts" / "lib" / "prompt_sanitize.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "prompt_sanitize.py").read_text()
    )
    (root / "opencode.json").write_text("CERBERUS_OPENCODE_JSON\n")
    (root / ".opencode" / "agents" / f"{perspective}.md").write_text("CERBERUS_AGENT\n")


@pytest.fixture(autouse=True)
def cleanup_tmp_outputs() -> None:
    """Keep /tmp artifacts from one test from leaking into others."""
    suffixes = (
        "parse-input", "output.txt", "stderr.log", "exitcode", "review.md",
        "timeout-marker.txt", "fast-path-prompt.md", "fast-path-output.txt",
        "fast-path-stderr.log", "model-used", "primary-model", "reviewer-name",
        "configured-model",
    )
    Path("/tmp/opencode_calls.log").unlink(missing_ok=True)
    for perspective in ("security", "correctness"):
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)
    yield
    Path("/tmp/opencode_calls.log").unlink(missing_ok=True)
    for perspective in ("security", "correctness"):
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)


class TestModelPool:
    """Tests for model pool random assignment."""

    def test_tiered_model_pool_selects_requested_tier(self, tmp_path: Path) -> None:
        """When MODEL_TIER is set and tier exists, select from that tier pool."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"
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
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        env = make_env(bin_dir, diff_file, cerberus_root)
        env["MODEL_TIER"] = "flash"

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        model = Path("/tmp/security-primary-model").read_text().strip()
        assert model in {"openrouter/flash-a", "openrouter/flash-b"}

    def test_requested_tier_falls_back_to_standard_tier(self, tmp_path: Path) -> None:
        """When requested tier is empty, fallback to configured standard tier."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"
  pool:
    - "openrouter/legacy-a"
    - "openrouter/legacy-b"
  tiers:
    standard:
      - "openrouter/standard-a"
      - "openrouter/standard-b"

reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        env = make_env(bin_dir, diff_file, cerberus_root)
        env["MODEL_TIER"] = "pro"

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        model = Path("/tmp/security-primary-model").read_text().strip()
        assert model in {"openrouter/standard-a", "openrouter/standard-b"}

    def test_requested_tier_falls_back_to_unscoped_pool(self, tmp_path: Path) -> None:
        """When requested and standard tiers are absent, fallback to legacy model.pool."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"
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
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        env = make_env(bin_dir, diff_file, cerberus_root)
        env["MODEL_TIER"] = "pro"

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        model = Path("/tmp/security-primary-model").read_text().strip()
        assert model in {"openrouter/legacy-a", "openrouter/legacy-b"}

    def test_model_pool_selects_random_model_from_pool(self, tmp_path: Path) -> None:
        """When reviewer has model: pool, a random model from pool is selected."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        # Stub opencode that records the model it was called with
        make_executable(
            bin_dir / "opencode",
            '#!/usr/bin/env bash\n'
            'echo "model=$1" >> /tmp/opencode_calls.log\n'
            'cat <<\'REVIEW\'\n'
            '```json\n'
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Stub","findings":[],'
            '"stats":{"files_reviewed":1,"files_with_issues":0,"critical":0,"major":0,"minor":0,"info":0}}\n'
            '```\n'
            'REVIEW\n',
        )

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"
  pool:
    - "openrouter/model-a"
    - "openrouter/model-b"
    - "openrouter/model-c"

reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        # Run multiple times to verify randomness
        selected_models = set()
        for _ in range(10):
            result = subprocess.run(
                [str(RUN_REVIEWER), "security"],
                env=make_env(bin_dir, diff_file, cerberus_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"

            # Read the model that was written to primary-model file
            primary_model_file = Path("/tmp/security-primary-model")
            if primary_model_file.exists():
                selected_models.add(primary_model_file.read_text().strip())

        # Should have selected multiple distinct models across 10 runs
        assert len(selected_models) > 1, f"Expected diversity, got only: {selected_models}"
        # All selections should be from the pool
        pool_models = {"openrouter/model-a", "openrouter/model-b", "openrouter/model-c"}
        assert selected_models.issubset(pool_models), f"Got unexpected models: {selected_models}"

    def test_per_reviewer_model_pinning_still_works(self, tmp_path: Path) -> None:
        """When reviewer has a specific model, that model is used (backward compat)."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"
  pool:
    - "openrouter/model-a"
    - "openrouter/model-b"

reviewers:
  - name: SENTINEL
    perspective: security
    model: "openrouter/specific-model"
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=make_env(bin_dir, diff_file, cerberus_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

        primary_model = Path("/tmp/security-primary-model").read_text().strip()
        assert primary_model == "openrouter/specific-model"

    def test_input_model_override_takes_precedence(self, tmp_path: Path) -> None:
        """OPENCODE_MODEL env var still overrides everything."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"
  pool:
    - "openrouter/model-a"
    - "openrouter/model-b"

reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        env = make_env(bin_dir, diff_file, cerberus_root)
        env["OPENCODE_MODEL"] = "openrouter/override-model"

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

        primary_model = Path("/tmp/security-primary-model").read_text().strip()
        assert primary_model == "openrouter/override-model"

        configured_model = Path("/tmp/security-configured-model").read_text().strip()
        assert configured_model in {"openrouter/model-a", "openrouter/model-b"}

        assert (
            "::warning::Model override active for SENTINEL (security): using 'openrouter/override-model'"
            in result.stdout
        )

    def test_redundant_input_model_override_emits_notice(self, tmp_path: Path) -> None:
        """When OPENCODE_MODEL matches configured model, emit notice (not warning)."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"

reviewers:
  - name: SENTINEL
    perspective: security
    model: "openrouter/specific-model"
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        env = make_env(bin_dir, diff_file, cerberus_root)
        env["OPENCODE_MODEL"] = "openrouter/specific-model"

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

        configured_model = Path("/tmp/security-configured-model").read_text().strip()
        assert configured_model == "openrouter/specific-model"

        assert (
            "::notice::Model override set for SENTINEL (security) but matches configured model ('openrouter/specific-model')"
            in result.stdout
        )

    def test_fallback_when_no_pool_defined(self, tmp_path: Path) -> None:
        """When pool is not defined but reviewer uses pool, fall back to default."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"

reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=make_env(bin_dir, diff_file, cerberus_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

        primary_model = Path("/tmp/security-primary-model").read_text().strip()
        assert primary_model == "openrouter/moonshotai/kimi-k2.5"

    def test_model_logged_and_persisted_for_downstream(self, tmp_path: Path) -> None:
        """Selected model is logged and written to files for downstream steps."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"
  pool:
    - "openrouter/model-a"
    - "openrouter/model-b"

reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=make_env(bin_dir, diff_file, cerberus_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

        # Check that model-used file is written
        model_used_file = Path("/tmp/security-model-used")
        assert model_used_file.exists()
        model_used = model_used_file.read_text().strip()
        assert model_used in {"openrouter/model-a", "openrouter/model-b"}

        # Check logged in stdout
        assert "model_used=" in result.stdout

    def test_mixed_reviewers_some_pool_some_pinned(self, tmp_path: Path) -> None:
        """Cerberus can have some reviewers using pool and others pinned."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/default-model"
  pool:
    - "openrouter/pool-model-1"
    - "openrouter/pool-model-2"

reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
  - name: APOLLO
    perspective: correctness
    model: "openrouter/pinned-model"
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config, perspective="security")
        # Also need correctness agent
        (cerberus_root / ".opencode" / "agents" / "correctness.md").write_text("AGENT\n")

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        # Test security (uses pool)
        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=make_env(bin_dir, diff_file, cerberus_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        security_model = Path("/tmp/security-primary-model").read_text().strip()
        assert security_model in {"openrouter/pool-model-1", "openrouter/pool-model-2"}

        # Test correctness (uses pinned)
        result = subprocess.run(
            [str(RUN_REVIEWER), "correctness"],
            env=make_env(bin_dir, diff_file, cerberus_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        correctness_model = Path("/tmp/correctness-primary-model").read_text().strip()
        assert correctness_model == "openrouter/pinned-model"

    def test_pool_does_not_bleed_into_fallback(self, tmp_path: Path) -> None:
        """Pool parser stops at fallback: section and doesn't include its items."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"
  pool:
    - "openrouter/pool-only"
  fallback:
    - "openrouter/fallback-only"

reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        # Run several times; all should pick pool-only, never fallback-only
        for _ in range(5):
            result = subprocess.run(
                [str(RUN_REVIEWER), "security"],
                env=make_env(bin_dir, diff_file, cerberus_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0
            model = Path("/tmp/security-primary-model").read_text().strip()
            assert model == "openrouter/pool-only", f"Got fallback model: {model}"

    def test_inline_comments_stripped_from_pool_entries(self, tmp_path: Path) -> None:
        """Inline YAML comments after pool model names are stripped."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        write_stub_opencode(bin_dir / "opencode")

        cerberus_root = tmp_path / "cerberus-root"
        config = '''
model:
  default: "openrouter/moonshotai/kimi-k2.5"
  pool:
    - "openrouter/model-a"  # fast model
    - "openrouter/model-b"  # smart model

reviewers:
  - name: SENTINEL
    perspective: security
    model: pool
'''
        write_fake_cerberus_root(cerberus_root, config_yml=config)

        diff_file = tmp_path / "test.diff"
        write_simple_diff(diff_file)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=make_env(bin_dir, diff_file, cerberus_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        model = Path("/tmp/security-primary-model").read_text().strip()
        assert model in {"openrouter/model-a", "openrouter/model-b"}, (
            f"Comment leaked into model name: {model!r}"
        )
