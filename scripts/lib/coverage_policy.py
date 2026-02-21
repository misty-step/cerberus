"""Reads and validates coverage-policy.yml.

Single source of truth for coverage floors so thresholds can be advanced
by editing one file rather than CI YAML surgery.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Resolve relative to this file: scripts/lib/ → repo root
POLICY_FILE = Path(__file__).parent.parent.parent / "coverage-policy.yml"


@dataclass(frozen=True)
class CoveragePolicy:
    global_floor: int        # % — minimum line AND branch coverage
    patch_threshold: int     # % — minimum coverage for changed lines on PRs
    ratchet_steps: list[int] # ascending history of ratchet targets


def validate_policy(data: dict) -> None:
    """Validate a coverage policy dict. Raises ValueError with a descriptive message."""
    if not isinstance(data, dict):
        raise ValueError("coverage-policy.yml must contain a mapping of policy keys")

    for key in ("global_floor", "patch_threshold", "ratchet_steps"):
        if key not in data:
            raise ValueError(f"coverage-policy.yml missing required key: {key!r}")

    floor = data["global_floor"]
    if not isinstance(floor, int) or not (0 <= floor <= 100):
        raise ValueError(
            f"global_floor must be an integer in [0, 100], got {floor!r}"
        )

    patch = data["patch_threshold"]
    if not isinstance(patch, int) or not (0 <= patch <= 100):
        raise ValueError(
            f"patch_threshold must be an integer in [0, 100], got {patch!r}"
        )

    steps = data["ratchet_steps"]
    if not isinstance(steps, list) or not all(isinstance(s, int) for s in steps):
        raise ValueError("ratchet_steps must be a list of integers")

    for i in range(1, len(steps)):
        if steps[i] <= steps[i - 1]:
            raise ValueError(
                f"ratchet_steps must be strictly ascending; "
                f"got {steps[i - 1]} then {steps[i]}"
            )

    if floor not in steps:
        raise ValueError(
            f"global_floor {floor} must be one of the ratchet_steps {steps}"
        )


def load_policy(path: Path = POLICY_FILE) -> CoveragePolicy:
    """Load and validate coverage policy from a YAML file.

    Raises:
        FileNotFoundError: if the policy file does not exist.
        ValueError: if the policy is malformed.
    """
    if not path.exists():
        raise FileNotFoundError(f"Coverage policy file not found: {path}")

    with path.open() as f:
        data = yaml.safe_load(f)

    validate_policy(data)

    return CoveragePolicy(
        global_floor=int(data["global_floor"]),
        patch_threshold=int(data["patch_threshold"]),
        ratchet_steps=[int(s) for s in data["ratchet_steps"]],
    )
