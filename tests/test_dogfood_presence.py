"""Tests for dogfood presence configuration and classification taxonomy."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent
DOGFOOD_CONFIG = ROOT / "defaults" / "dogfood.yml"
BENCHMARK_README = ROOT / "docs" / "reviewer-benchmark" / "README.md"


def _load_dogfood() -> dict:
    return yaml.safe_load(DOGFOOD_CONFIG.read_text(encoding="utf-8"))


# --- Config structure tests ---


def test_dogfood_config_exists() -> None:
    assert DOGFOOD_CONFIG.exists(), "defaults/dogfood.yml must exist"


def test_dogfood_config_defines_core_repos() -> None:
    config = _load_dogfood()
    repos = config["core_repos"]
    assert isinstance(repos, list)
    assert len(repos) >= 3, "At least 3 core repos expected"
    for entry in repos:
        assert "repo" in entry, "Each core repo needs a 'repo' field"
        assert "min_presence" in entry, "Each core repo needs a 'min_presence' field"
        assert 0.0 < entry["min_presence"] <= 1.0, (
            f"min_presence for {entry['repo']} must be between 0 and 1"
        )


def test_dogfood_config_includes_cerberus_repo() -> None:
    config = _load_dogfood()
    repo_names = [r["repo"] for r in config["core_repos"]]
    assert "misty-step/cerberus" in repo_names, (
        "cerberus must be a core dogfood repo"
    )


def test_dogfood_config_defines_classification_taxonomy() -> None:
    config = _load_dogfood()
    classification = config["classification"]
    required_buckets = {"absent", "skipped", "present_clean", "present_with_skips"}
    assert required_buckets == set(classification.keys()), (
        f"Classification must define exactly {required_buckets}"
    )
    for bucket, description in classification.items():
        assert isinstance(description, str), f"{bucket} must have a string description"
        assert len(description) > 20, f"{bucket} description is too short"


def test_dogfood_config_defines_window() -> None:
    config = _load_dogfood()
    assert "window_days" in config
    assert isinstance(config["window_days"], int)
    assert config["window_days"] > 0


# --- Benchmark README taxonomy documentation ---


def test_benchmark_readme_documents_classification() -> None:
    readme = BENCHMARK_README.read_text(encoding="utf-8")
    assert "absent" in readme.lower()
    assert "skipped" in readme.lower()
    assert "present" in readme.lower()
    assert "classification" in readme.lower() or "taxonomy" in readme.lower()


def test_benchmark_readme_references_dogfood_config() -> None:
    readme = BENCHMARK_README.read_text(encoding="utf-8")
    assert "dogfood.yml" in readme


# --- Presence check script tests ---


def test_presence_check_script_exists() -> None:
    script = ROOT / "scripts" / "check-dogfood-presence.py"
    assert script.exists(), "scripts/check-dogfood-presence.py must exist"


def test_presence_check_script_is_importable() -> None:
    """The script should define a classify_pr function we can test."""
    mod = _import_script()
    assert hasattr(mod, "classify_pr"), "Script must define classify_pr()"
    assert hasattr(mod, "load_config"), "Script must define load_config()"
    assert hasattr(mod, "classify_pr_from_checks"), "Script must define classify_pr_from_checks()"
    assert hasattr(mod, "summarize_presence"), "Script must define summarize_presence()"


def test_classify_pr_absent() -> None:
    mod = _import_script()
    result = mod.classify_pr(
        cerberus_workflow_ran=False,
        preflight_skipped=False,
        reviewer_skips=0,
        total_reviewers=0,
    )
    assert result == "absent"


def test_classify_pr_skipped() -> None:
    mod = _import_script()
    result = mod.classify_pr(
        cerberus_workflow_ran=True,
        preflight_skipped=True,
        reviewer_skips=0,
        total_reviewers=0,
    )
    assert result == "skipped"


def test_classify_pr_present_clean() -> None:
    mod = _import_script()
    result = mod.classify_pr(
        cerberus_workflow_ran=True,
        preflight_skipped=False,
        reviewer_skips=0,
        total_reviewers=6,
    )
    assert result == "present_clean"


def test_classify_pr_present_with_skips() -> None:
    mod = _import_script()
    result = mod.classify_pr(
        cerberus_workflow_ran=True,
        preflight_skipped=False,
        reviewer_skips=2,
        total_reviewers=6,
    )
    assert result == "present_with_skips"


def test_load_config_returns_core_repos() -> None:
    mod = _import_script()
    config = mod.load_config()
    assert "core_repos" in config
    assert len(config["core_repos"]) >= 3


# --- classify_pr_from_checks tests ---


def test_classify_from_checks_no_cerberus() -> None:
    mod = _import_script()
    pr = {"number": 1, "statusCheckRollup": [
        {"name": "lint", "conclusion": "SUCCESS"},
        {"name": "test", "conclusion": "SUCCESS"},
    ]}
    assert mod.classify_pr_from_checks(pr) == "absent"


def test_classify_from_checks_preflight_skipped() -> None:
    mod = _import_script()
    pr = {"number": 2, "statusCheckRollup": [
        {"name": "review / Cerberus · preflight", "conclusion": "SKIPPED"},
    ]}
    assert mod.classify_pr_from_checks(pr) == "skipped"


def test_classify_from_checks_clean_run() -> None:
    mod = _import_script()
    pr = {"number": 3, "statusCheckRollup": [
        {"name": "review / Cerberus · preflight", "conclusion": "SUCCESS"},
        {"name": "review / Cerberus · wave1 · Correctness", "conclusion": "SUCCESS"},
        {"name": "review / Cerberus · wave1 · Security", "conclusion": "SUCCESS"},
        {"name": "review / Cerberus · gate wave1", "conclusion": "SUCCESS"},
        {"name": "review / Cerberus", "conclusion": "SUCCESS"},
    ]}
    assert mod.classify_pr_from_checks(pr) == "present_clean"


def test_classify_from_checks_with_skips() -> None:
    mod = _import_script()
    pr = {"number": 4, "statusCheckRollup": [
        {"name": "review / Cerberus · preflight", "conclusion": "SUCCESS"},
        {"name": "review / Cerberus · wave1 · Correctness", "conclusion": "SUCCESS"},
        {"name": "review / Cerberus · wave1 · Security", "conclusion": "SKIPPED"},
        {"name": "review / Cerberus · wave1 · Testing", "conclusion": "SUCCESS"},
    ]}
    assert mod.classify_pr_from_checks(pr) == "present_with_skips"


def test_classify_from_checks_empty_rollup() -> None:
    mod = _import_script()
    pr = {"number": 5, "statusCheckRollup": []}
    assert mod.classify_pr_from_checks(pr) == "absent"


def test_classify_from_checks_missing_rollup_key() -> None:
    mod = _import_script()
    pr = {"number": 6}
    assert mod.classify_pr_from_checks(pr) == "absent"


def test_classify_from_checks_null_rollup() -> None:
    mod = _import_script()
    pr = {"number": 7, "statusCheckRollup": None}
    assert mod.classify_pr_from_checks(pr) == "absent"


def test_classify_from_checks_cerberus_ran_but_no_reviewers() -> None:
    """Cerberus ran (preflight succeeded) but no wave checks → skipped."""
    mod = _import_script()
    pr = {"number": 8, "statusCheckRollup": [
        {"name": "review / Cerberus · preflight", "conclusion": "SUCCESS"},
        {"name": "review / Cerberus", "conclusion": "SUCCESS"},
    ]}
    assert mod.classify_pr_from_checks(pr) == "skipped"


def test_classify_pr_zero_reviewers_is_skipped() -> None:
    """When Cerberus ran but total_reviewers=0, classify as skipped."""
    mod = _import_script()
    result = mod.classify_pr(
        cerberus_workflow_ran=True,
        preflight_skipped=False,
        reviewer_skips=0,
        total_reviewers=0,
    )
    assert result == "skipped"


# --- summarize_presence tests ---


def test_summarize_presence_mixed() -> None:
    mod = _import_script()
    prs = [
        {"number": 1, "statusCheckRollup": []},  # absent
        {"number": 2, "statusCheckRollup": [
            {"name": "review / Cerberus · preflight", "conclusion": "SUCCESS"},
            {"name": "review / Cerberus · wave1 · Correctness", "conclusion": "SUCCESS"},
        ]},  # present_clean
        {"number": 3, "statusCheckRollup": [
            {"name": "review / Cerberus · preflight", "conclusion": "SUCCESS"},
            {"name": "review / Cerberus · wave1 · Correctness", "conclusion": "SKIPPED"},
        ]},  # present_with_skips
    ]
    result = mod.summarize_presence("test/repo", prs)
    assert result["repo"] == "test/repo"
    assert result["total_prs"] == 3
    assert result["presence_rate"] == 0.667
    assert result["classifications"]["absent"] == 1
    assert result["classifications"]["present_clean"] == 1
    assert result["classifications"]["present_with_skips"] == 1


def test_summarize_presence_empty() -> None:
    mod = _import_script()
    result = mod.summarize_presence("test/repo", [])
    assert result["total_prs"] == 0
    assert result["presence_rate"] == 0.0


def test_summarize_presence_all_present() -> None:
    mod = _import_script()
    prs = [
        {"number": i, "statusCheckRollup": [
            {"name": "review / Cerberus · preflight", "conclusion": "SUCCESS"},
            {"name": "review / Cerberus · wave1 · Correctness", "conclusion": "SUCCESS"},
        ]}
        for i in range(1, 6)
    ]
    result = mod.summarize_presence("test/repo", prs)
    assert result["presence_rate"] == 1.0
    assert result["classifications"]["present_clean"] == 5


# --- Helpers ---


def _import_script():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_dogfood_presence",
        ROOT / "scripts" / "check-dogfood-presence.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
