"""Tests for lib.coverage_policy."""

from pathlib import Path

import pytest

from lib.coverage_policy import CoveragePolicy, POLICY_FILE, load_policy, validate_policy


def write_policy(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "coverage-policy.yml"
    path.write_text(content)
    return path


def valid_policy_yaml() -> str:
    return """
global_floor: 70
patch_threshold: 90
ratchet_steps: [30, 45, 60, 70, 80]
"""


def test_load_policy_returns_dataclass(tmp_path):
    path = write_policy(tmp_path, valid_policy_yaml())
    policy = load_policy(path)
    assert isinstance(policy, CoveragePolicy)
    assert policy.global_floor == 70
    assert policy.patch_threshold == 90
    assert policy.ratchet_steps == [30, 45, 60, 70, 80]


def test_load_policy_file_not_found(tmp_path):
    path = tmp_path / "missing-policy.yml"
    with pytest.raises(FileNotFoundError):
        load_policy(path)


def test_validate_policy_missing_global_floor():
    data = {"patch_threshold": 90, "ratchet_steps": [70, 80]}
    with pytest.raises(ValueError, match="global_floor"):
        validate_policy(data)


def test_validate_policy_missing_patch_threshold():
    data = {"global_floor": 70, "ratchet_steps": [70, 80]}
    with pytest.raises(ValueError, match="patch_threshold"):
        validate_policy(data)


def test_validate_policy_missing_ratchet_steps():
    data = {"global_floor": 70, "patch_threshold": 90}
    with pytest.raises(ValueError, match="ratchet_steps"):
        validate_policy(data)


@pytest.mark.parametrize("floor", [-1, 101])
def test_validate_policy_floor_out_of_range(floor):
    data = {"global_floor": floor, "patch_threshold": 90, "ratchet_steps": [floor]}
    with pytest.raises(ValueError, match="global_floor"):
        validate_policy(data)


def test_validate_policy_floor_not_in_ratchet_steps():
    data = {"global_floor": 70, "patch_threshold": 90, "ratchet_steps": [30, 45, 60]}
    with pytest.raises(ValueError, match="global_floor"):
        validate_policy(data)


def test_validate_policy_ratchet_not_ascending():
    data = {"global_floor": 70, "patch_threshold": 90, "ratchet_steps": [30, 70, 60, 80]}
    with pytest.raises(ValueError, match="ascending"):
        validate_policy(data)


def test_load_policy_from_actual_file():
    policy = load_policy(POLICY_FILE)
    assert policy.global_floor == 70
    assert policy.patch_threshold == 90
    assert policy.ratchet_steps == [30, 45, 60, 70, 80]
