"""Runtime facade primitives for reviewer execution.

This module defines a framework-agnostic execution contract and a Pi engine
implementation for single review attempts.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeAttemptRequest:
    perspective: str
    provider: str
    model: str
    prompt_file: Path
    system_prompt_file: Path
    timeout_seconds: int
    tools: list[str]
    extensions: list[str]
    skills: list[str]
    thinking_level: str | None
    api_key: str
    agent_dir: Path
    isolated_home: Path
    max_steps: int | None = None
    trusted_system_prompt_file: Path | None = None
    telemetry_file: Path | None = None
    prompt_capture_path: str | None = None


@dataclass(frozen=True)
class RuntimeAttemptResult:
    exit_code: int
    timed_out: bool
    stdout: str
    stderr: str
    error_type: str  # none | transient | permanent | timeout | unknown
    error_class: str  # specific classifier
    retry_after_seconds: int | None = None


def _extract_retry_after_seconds(text: str) -> int | None:
    match = re.search(r"retry[-_ ]after[\" ]*[:=][ ]*(\d+)", text, re.IGNORECASE)
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def classify_runtime_error(*, stdout: str, stderr: str, exit_code: int) -> tuple[str, str, int | None]:
    """Classify runtime failure with Cerberus-compatible taxonomy."""

    if exit_code == 0:
        return "none", "none", None
    if exit_code == 124:
        return "timeout", "timeout", None

    combined = f"{stdout}\n{stderr}".lower()

    if re.search(
        r"incorrect_api_key|invalid_api_key|invalid.api.key|exceeded_current_quota|insufficient_quota|"
        r"insufficient.credits|payment.required|quota.exceeded|credits.depleted|credits.exhausted|"
        r"no.cookie.auth|no credentials found|authentication failed|unauthorized|missing authentication header|"
        r"http[^0-9]*401",
        combined,
    ):
        return "permanent", "auth_or_quota", None

    if re.search(r"rate.limit|too many requests|retry-after|http[^0-9]*429|error[^0-9]*429", combined):
        return "transient", "rate_limit", _extract_retry_after_seconds(combined)

    if re.search(r"http[^0-9]*5[0-9]{2}|error[^0-9]*5[0-9]{2}|service.unavailable|temporarily.unavailable", combined):
        return "transient", "server_5xx", None

    if re.search(
        r"network.*(error|timeout|unreachable)|timed out|timeout while|connection (reset|refused|aborted)|"
        r"temporary failure|tls handshake timeout|econn(reset|refused)|enotfound|broken pipe|"
        r"remote end closed connection",
        combined,
    ):
        return "transient", "network", None

    if re.search(r"provider returned error|provider.error|upstream.error|model.error", combined):
        return "transient", "provider_generic", None

    if re.search(r"http[^0-9]*4([0-1][0-9]|2[0-8]|[3-9][0-9])|error[^0-9]*4([0-1][0-9]|2[0-8]|[3-9][0-9])", combined):
        return "permanent", "client_4xx", None

    return "unknown", "unknown", None


def _normalize_model_for_provider(model: str, provider: str) -> str:
    """Convert provider-prefixed model values into provider-local model IDs.

    Example:
      provider=openrouter, model=openrouter/moonshotai/kimi-k2.5
      -> moonshotai/kimi-k2.5
    """

    prefix = f"{provider}/"
    return model[len(prefix) :] if model.startswith(prefix) else model


def build_pi_command(req: RuntimeAttemptRequest) -> list[str]:
    model_id = _normalize_model_for_provider(req.model, req.provider)

    cmd = [
        "pi",
        "--provider",
        req.provider,
        "--model",
        model_id,
        "--api-key",
        req.api_key,
        "--no-session",
        "--tools",
        ",".join(req.tools),
        "--system-prompt",
        str(req.system_prompt_file),
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--print",
    ]

    if req.thinking_level:
        cmd.extend(["--thinking", req.thinking_level])

    for ext in req.extensions:
        cmd.extend(["--extension", ext])

    for skill in req.skills:
        cmd.extend(["--skill", skill])

    return cmd


def run_pi_attempt(req: RuntimeAttemptRequest) -> RuntimeAttemptResult:
    """Execute one Pi attempt and return a normalized result."""

    cmd = build_pi_command(req)

    try:
        prompt_text = req.prompt_file.read_text()
    except OSError as exc:
        stdout = ""
        stderr = f"unable to read prompt file {req.prompt_file}: {exc}"
        error_type, error_class, retry_after = classify_runtime_error(
            stdout=stdout,
            stderr=stderr,
            exit_code=1,
        )
        return RuntimeAttemptResult(
            exit_code=1,
            timed_out=False,
            stdout=stdout,
            stderr=stderr,
            error_type=error_type,
            error_class=error_class,
            retry_after_seconds=retry_after,
        )

    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(req.isolated_home),
        "XDG_CONFIG_HOME": str(req.isolated_home / ".config"),
        "XDG_DATA_HOME": str(req.isolated_home / ".local/share"),
        "TMPDIR": str(req.isolated_home / "tmp"),
        "PI_CODING_AGENT_DIR": str(req.agent_dir),
        "PI_SKIP_VERSION_CHECK": "1",
        # Kept for compatibility with scripts/extensions expecting these names.
        "OPENROUTER_API_KEY": req.api_key,
        "CERBERUS_OPENROUTER_API_KEY": req.api_key,
    }

    if os.environ.get("LANG"):
        env["LANG"] = os.environ["LANG"]
    if os.environ.get("LC_ALL"):
        env["LC_ALL"] = os.environ["LC_ALL"]

    if req.max_steps is not None and req.max_steps > 0:
        env["CERBERUS_MAX_STEPS"] = str(req.max_steps)
    if req.trusted_system_prompt_file is not None:
        env["CERBERUS_TRUSTED_SYSTEM_PROMPT_FILE"] = str(req.trusted_system_prompt_file)
    if req.telemetry_file is not None:
        env["CERBERUS_RUNTIME_TELEMETRY_FILE"] = str(req.telemetry_file)
    if req.prompt_capture_path:
        env["CERBERUS_PROMPT_CAPTURE_PATH"] = str(req.prompt_capture_path)

    try:
        proc = subprocess.run(
            cmd,
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=req.timeout_seconds,
            env=env,
        )
        error_type, error_class, retry_after = classify_runtime_error(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
        return RuntimeAttemptResult(
            exit_code=proc.returncode,
            timed_out=False,
            stdout=proc.stdout,
            stderr=proc.stderr,
            error_type=error_type,
            error_class=error_class,
            retry_after_seconds=retry_after,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if not isinstance(stdout, str):
            stdout = stdout.decode("utf-8", errors="replace")
        if not isinstance(stderr, str):
            stderr = stderr.decode("utf-8", errors="replace")
        return RuntimeAttemptResult(
            exit_code=124,
            timed_out=True,
            stdout=stdout,
            stderr=stderr,
            error_type="timeout",
            error_class="timeout",
            retry_after_seconds=None,
        )
