"""Cerberus consumer workflow validator.

Goal: fail fast on common misconfigs with actionable GitHub Actions annotations.

Note: GitHub Actions workflow YAML uses the key `on:` which PyYAML (YAML 1.1)
can misparse as boolean True. We disable bool resolution for on/off/yes/no.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Finding:
    """Data class for Finding."""
    level: str  # "error" | "warning"
    message: str


def _workflow_yaml_loader() -> type[yaml.SafeLoader]:
    class Loader(yaml.SafeLoader):
        """Data class for Loader."""
        pass

    # Prevent YAML 1.1 implicit bool coercion of keys like "on:" / "off:".
    # Keep true/false parsing (t/T/f/F) intact.
    for ch in "OoYyNn":
        resolvers = Loader.yaml_implicit_resolvers.get(ch)
        if not resolvers:
            continue
        Loader.yaml_implicit_resolvers[ch] = [
            (tag, regexp)
            for (tag, regexp) in resolvers
            if tag != "tag:yaml.org,2002:bool"
        ]

    return Loader


_WORKFLOW_LOADER = _workflow_yaml_loader()


def _extract_events(on_block: Any) -> set[str]:
    if on_block is None:
        return set()
    if isinstance(on_block, str):
        return {on_block}
    if isinstance(on_block, list):
        return {str(x) for x in on_block}
    if isinstance(on_block, dict):
        return {str(k) for k in on_block.keys()}
    return set()


def _cerberus_action_kind(uses: str) -> str | None:
    prefix = "misty-step/cerberus"
    if not uses.startswith(prefix):
        return None
    rest = uses[len(prefix) :]
    if rest.startswith("@"):
        return "review"
    if rest.startswith("/draft-check@"):
        return "draft-check"
    if rest.startswith("/verdict@"):
        return "verdict"
    if rest.startswith("/triage@"):
        return "triage"
    if rest.startswith("/matrix@"):
        return "matrix"
    if rest.startswith("/validate@"):
        return "validate"
    return "other"


def _with(step: dict[str, Any], key: str) -> Any | None:
    with_block = step.get("with")
    if isinstance(with_block, dict):
        return with_block.get(key)
    return None


def _comment_policy(step: dict[str, Any]) -> tuple[str, bool]:
    """Return the effective per-reviewer comment policy for the review action.

    Canonical input: `comment-policy` (docs/templates).
    Back-compat input: `post-comment`.
    """
    raw = _with(step, "comment-policy")
    # Match action.yml behavior: empty comment-policy is falsy and falls back to
    # post-comment.
    if raw is not None and str(raw).strip() == "":
        raw = None
    if raw is None:
        raw = _with(step, "post-comment")
    if raw is None:
        return ("never", False)

    s = str(raw).strip().lower()
    if s in {"", "never", "false", "0", "no", "n", "off"}:
        return ("never", False)
    if s in {"always", "non-pass"}:
        return (s, False)
    if s in {"true", "1", "yes", "y", "on"}:
        return ("always", False)
    return ("never", True)


def _boolish(value: Any | None, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "y", "on"}:
        return True
    if s in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _is_gha_expression(value: Any) -> bool:
    """Return True when value looks like a GitHub Actions expression (${{ … }})."""
    return isinstance(value, str) and "${{" in value


_COE_REMEDIATION = (
    "Prefer v2 fallback models, fail-on-skip, or triage rather than continue-on-error."
)

_V1_UPGRADE_GUIDANCE = (
    "Upgrade to v2: see docs/MIGRATION.md for the full migration guide "
    "or templates/consumer-workflow-reusable.yml for the recommended setup. "
    "v2 includes reliability hardening (empty-output retries, model fallback chain, parse-failure recovery, "
    "timeout fast-path fallback, staged OpenCode config, isolated HOME) "
    "and supports fail-on-skip to turn SKIPs into CI failures."
)


def _coe_finding(source: str, job_name: str, *, scope: str, uses: str | None = None, coe_val: Any = None) -> Finding:
    """Build a continue-on-error warning Finding.

    scope: "step" (per-step) or "job" (job-level).
    uses:  the `uses:` string (required for step scope).
    coe_val: the raw expression value (set for expression-based warnings).
    """
    location = f"on `{uses}`" if scope == "step" else "at the job level"
    if coe_val is not None:
        detail = (
            f"sets `continue-on-error: {coe_val!r}` {location}. "
            "This expression may resolve to true at runtime, masking Cerberus failures and producing false-green checks."
        )
    else:
        qualifier = "all " if scope == "job" else ""
        detail = (
            f"sets `continue-on-error: true` {location}. "
            f"This masks {qualifier}Cerberus failures{'  in the job' if scope == 'job' else ''} and can produce false-green checks."
        )
    return Finding("warning", f"{source}: job `{job_name}` {detail} {_COE_REMEDIATION}")


def _effective_permissions(workflow: dict[str, Any], job: dict[str, Any]) -> Any | None:
    # Job-level permissions override workflow-level permissions.
    if "permissions" in job:
        return job.get("permissions")
    return workflow.get("permissions")


def _perm_allows(perms: Any | None, perm: str, need: str) -> bool | None:
    """Return True/False when explicit, else None when unknown/unset."""
    if perms is None:
        return None

    if isinstance(perms, str):
        p = perms.strip()
        if p == "read-all":
            return need == "read"
        if p == "write-all":
            return True
        if p == "none":
            return False
        return None

    if isinstance(perms, dict):
        # GitHub semantics: unspecified keys become "none" once a permissions
        # mapping exists at the workflow/job level.
        raw = perms.get(perm, "none")
        v = str(raw).strip()
        if v == "write":
            return True
        if v == "read":
            return need == "read"
        if v == "none":
            return False
        return None

    return None


def validate_workflow_dict(workflow: dict[str, Any], *, source: str) -> list[Finding]:
    """Validate workflow dict."""
    findings: list[Finding] = []

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return [Finding("error", f"{source}: missing top-level `jobs:` mapping")]

    # YAML 1.1 parsers can load `on:` as boolean True. We still guard in case
    # someone used a different loader upstream.
    on_block = workflow.get("on")
    if on_block is None and True in workflow:
        on_block = workflow.get(True)
    events = _extract_events(on_block)

    uses_cerberus = False

    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue

        perms = _effective_permissions(workflow, job)
        job_has_cerberus_action = False

        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str):
                continue
            kind = _cerberus_action_kind(uses)
            if kind is None:
                continue
            uses_cerberus = True

            # v1 usage check: warn on any cerberus @v1 step.
            # Catches bare @v1, semver tags like @v1.2.3, and subpath refs like @v1/path.
            ref = uses.rsplit("@", 1)[-1]
            if ref == "v1" or ref.startswith(("v1.", "v1/", "v1-")):
                findings.append(
                    Finding(
                        "warning",
                        f"{source}: job `{job_name}` uses `{uses}` which is v1. {_V1_UPGRADE_GUIDANCE}",
                    )
                )

            # continue-on-error check: review/verdict/triage only.
            # draft-check and matrix are excluded — they don't emit verdicts,
            # so masking their exit code doesn't hide review results.
            if kind in {"review", "verdict", "triage"}:
                job_has_cerberus_action = True
                coe_val = step.get("continue-on-error")
                if _boolish(coe_val, default=False):
                    findings.append(_coe_finding(source, job_name, scope="step", uses=uses))
                elif _is_gha_expression(coe_val):
                    findings.append(_coe_finding(source, job_name, scope="step", uses=uses, coe_val=coe_val))

            if kind in {"review", "draft-check", "verdict", "triage"}:
                if not _with(step, "github-token"):
                    findings.append(
                        Finding(
                            "error",
                            f"{source}: job `{job_name}` uses `{uses}` but is missing `with: github-token`",
                        )
                    )

            if kind == "draft-check":
                pr_write = _perm_allows(perms, "pull-requests", "write")
                if pr_write is False:
                    findings.append(
                        Finding(
                            "error",
                            f"{source}: job `{job_name}` uses `{uses}` but lacks `permissions: pull-requests: write` (required to post skip comment)",
                        )
                    )
                elif pr_write is None:
                    findings.append(
                        Finding(
                            "warning",
                            f"{source}: job `{job_name}` uses `{uses}` but has no explicit `permissions` for `pull-requests` (set `pull-requests: write` to post skip comment)",
                        )
                    )

            if kind == "review":
                pr_read = _perm_allows(perms, "pull-requests", "read")
                contents_read = _perm_allows(perms, "contents", "read")
                if pr_read is False:
                    findings.append(
                        Finding(
                            "error",
                            f"{source}: job `{job_name}` lacks `permissions: pull-requests: read` (required to fetch PR diff/context)",
                        )
                    )
                elif pr_read is None:
                    findings.append(
                        Finding(
                            "warning",
                            f"{source}: job `{job_name}` has no explicit `permissions` for `pull-requests` (defaults vary; set `pull-requests: read`)",
                        )
                    )

                if contents_read is False:
                    findings.append(
                        Finding(
                            "error",
                            f"{source}: job `{job_name}` lacks `permissions: contents: read`",
                        )
                    )
                elif contents_read is None:
                    findings.append(
                        Finding(
                            "warning",
                            f"{source}: job `{job_name}` has no explicit `permissions` for `contents` (defaults vary; set `contents: read`)",
                        )
                    )

                comment_policy, unknown_policy = _comment_policy(step)
                if unknown_policy:
                    findings.append(
                        Finding(
                            "warning",
                            f"{source}: job `{job_name}` sets an unknown comment policy; expected `comment-policy` (preferred) or legacy `post-comment` of never/non-pass/always/true/false. Cerberus will default to never.",
                        )
                    )

                if comment_policy != "never":
                    pr_write = _perm_allows(perms, "pull-requests", "write")
                    if pr_write is False:
                        findings.append(
                            Finding(
                                "error",
                                f"{source}: job `{job_name}` will post per-reviewer PR comments (comment policy is not `never`) but lacks `permissions: pull-requests: write`. Fix: set `comment-policy: 'never'` OR grant `pull-requests: write`.",
                            )
                        )
                    elif pr_write is None:
                        findings.append(
                            Finding(
                                "warning",
                                f"{source}: job `{job_name}` may post per-reviewer PR comments (comment policy is not `never`) but permissions are not explicit. Ensure `pull-requests: write` OR set `comment-policy: 'never'`.",
                            )
                        )

                if _with(step, "api-key") is None and _with(step, "kimi-api-key") is None:
                    findings.append(
                        Finding(
                            "warning",
                            f"{source}: job `{job_name}` uses `{uses}` without `with: api-key`. This is fine only if `CERBERUS_API_KEY`/`CERBERUS_OPENROUTER_API_KEY`/`OPENROUTER_API_KEY` is set at job env.",
                        )
                    )

            if kind == "verdict":
                pr_write = _perm_allows(perms, "pull-requests", "write")
                contents_read = _perm_allows(perms, "contents", "read")
                if pr_write is False:
                    findings.append(
                        Finding(
                            "error",
                            f"{source}: job `{job_name}` uses `{uses}` but lacks `permissions: pull-requests: write` (required to post verdict comment/review)",
                        )
                    )
                elif pr_write is None:
                    findings.append(
                        Finding(
                            "warning",
                            f"{source}: job `{job_name}` uses `{uses}` but has no explicit `permissions` for `pull-requests` (set `pull-requests: write`)",
                        )
                    )

                if contents_read is False:
                    findings.append(
                        Finding(
                            "error",
                            f"{source}: job `{job_name}` uses `{uses}` but lacks `permissions: contents: read` (required for checkout)",
                        )
                    )
                elif contents_read is None:
                    findings.append(
                        Finding(
                            "warning",
                            f"{source}: job `{job_name}` uses `{uses}` but has no explicit `permissions` for `contents` (set `contents: read`)",
                        )
                    )

            if kind == "triage":
                pr_write = _perm_allows(perms, "pull-requests", "write")
                contents_write = _perm_allows(perms, "contents", "write")
                if pr_write is False:
                    findings.append(
                        Finding(
                            "error",
                            f"{source}: job `{job_name}` uses `{uses}` but lacks `permissions: pull-requests: write`",
                        )
                    )
                elif pr_write is None:
                    findings.append(
                        Finding(
                            "warning",
                            f"{source}: job `{job_name}` uses `{uses}` but has no explicit `permissions` for `pull-requests` (set `pull-requests: write`)",
                        )
                    )

                if contents_write is False:
                    findings.append(
                        Finding(
                            "error",
                            f"{source}: job `{job_name}` uses `{uses}` but lacks `permissions: contents: write`",
                        )
                    )
                elif contents_write is None:
                    findings.append(
                        Finding(
                            "warning",
                            f"{source}: job `{job_name}` uses `{uses}` but has no explicit `permissions` for `contents` (set `contents: write`)",
                        )
                    )

        if job_has_cerberus_action:
            job_coe = job.get("continue-on-error")
            if _boolish(job_coe, default=False):
                findings.append(_coe_finding(source, job_name, scope="job"))
            elif _is_gha_expression(job_coe):
                findings.append(_coe_finding(source, job_name, scope="job", coe_val=job_coe))

    if uses_cerberus:
        if "pull_request_target" in events:
            findings.append(
                Finding(
                    "error",
                    f"{source}: workflow uses `pull_request_target`. Cerberus must run on `pull_request` (not `pull_request_target`) to avoid secret exposure.",
                )
            )
        if "pull_request" not in events:
            findings.append(
                Finding(
                    "error",
                    f"{source}: workflow does not declare `on: pull_request`. Cerberus review/verdict actions require a PR event payload.",
                )
            )

    return findings


def validate_workflow_file(path: Path) -> tuple[list[Finding], str | None]:
    """Validate workflow file."""
    try:
        raw = path.read_text()
    except OSError as exc:
        return ([Finding("error", f"{path}: unable to read workflow file: {exc}")], None)

    try:
        loaded = yaml.load(raw, Loader=_WORKFLOW_LOADER)
    except Exception as exc:  # noqa: BLE001 - show YAML error as user-facing ::error::
        return (
            [Finding("error", f"{path}: invalid YAML: {exc}")],
            None,
        )

    if not isinstance(loaded, dict):
        return ([Finding("error", f"{path}: workflow YAML must be a mapping")], None)

    findings = validate_workflow_dict(loaded, source=str(path))
    return (findings, None)


def _emit(findings: list[Finding]) -> None:
    for f in findings:
        if f.level == "error":
            print(f"::error::{f.message}")
        else:
            print(f"::warning::{f.message}")


def main() -> None:
    """Main."""
    parser = argparse.ArgumentParser(
        description="Validate a Cerberus consumer workflow for common misconfigurations."
    )
    parser.add_argument("workflow", help="Path to workflow file (e.g. .github/workflows/cerberus.yml)")
    parser.add_argument(
        "--fail-on-warnings",
        default="false",
        help="Exit non-zero when warnings exist (default: false)",
    )
    args = parser.parse_args()

    path = Path(args.workflow)
    findings, _ = validate_workflow_file(path)
    _emit(findings)

    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level != "error"]

    if errors:
        raise SystemExit(1)
    if _boolish(args.fail_on_warnings, default=False) and warnings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
