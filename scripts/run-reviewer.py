#!/usr/bin/env python3
"""Run one Cerberus reviewer perspective via Pi runtime.

This preserves Cerberus downstream contracts (parse/aggregate/verdict) while
migrating runtime execution from OpenCode to Pi.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Mapping

from lib.defaults_config import ConfigError, load_defaults_config
from lib.review_prompt import render_review_prompt_file
from lib.reviewer_profiles import (
    ReviewerProfilesError,
    RuntimeProfile,
    load_reviewer_profiles,
)
from lib.runtime_facade import (
    RuntimeAttemptRequest,
    classify_runtime_error,
    provider_api_key_env_var,
    run_pi_attempt,
)

BASE_DEFAULT_MODEL = "openrouter/moonshotai/kimi-k2.5"
MAX_RETRIES = 3


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_positive_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return value if value > 0 else default


def sanitize_model(value: str | None) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if len(s) >= 2 and ((s.startswith("\"") and s.endswith("\"")) or (s.startswith("'") and s.endswith("'"))):
        s = s[1:-1]
    return s.strip()


def normalize_tier(value: str | None) -> str:
    tier = (value or "standard").strip().lower()
    return tier or "standard"


def normalize_wave(value: str | None) -> str:
    wave = (value or "").strip().lower()
    return wave


def resolve_api_key_for_provider(provider: str, env: Mapping[str, str]) -> tuple[str, str]:
    key_var = provider_api_key_env_var(provider)
    api_key = sanitize_model(env.get(key_var))
    if key_var == "OPENROUTER_API_KEY" and not api_key:
        api_key = sanitize_model(env.get("CERBERUS_OPENROUTER_API_KEY"))
    return key_var, api_key


def default_backoff_seconds(retry_attempt: int) -> int:
    if retry_attempt == 1:
        return 2
    if retry_attempt == 2:
        return 4
    return 8


def maybe_sleep(seconds: int) -> None:
    if seconds <= 0:
        return
    if os.environ.get("CERBERUS_TEST_NO_SLEEP", "") == "1":
        return
    time.sleep(seconds)


def get_remaining_timeout(start_time: float, original_timeout: int) -> int:
    elapsed = int(time.time() - start_time)
    remaining = original_timeout - elapsed
    return remaining if remaining > 0 else 0


def has_valid_json_block(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    text = read_text(path)
    return bool(re.search(r"```json\s*\{.*?\}\s*```", text, re.DOTALL))


def extract_diff_files(diff_file: Path) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for line in read_text(diff_file).splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.strip().split()
        if len(parts) < 4:
            continue
        path_b = parts[3]
        if path_b.startswith("b/"):
            path_b = path_b[2:]
        if path_b and path_b not in seen:
            seen.add(path_b)
            files.append(path_b)
            if len(files) >= 20:
                break
    return files


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + 5 :]


def resolve_profile(cerberus_root: Path, perspective: str) -> RuntimeProfile:
    profiles_path = cerberus_root / "defaults" / "reviewer-profiles.yml"
    if not profiles_path.exists():
        if os.environ.get("CERBERUS_ALLOW_MISSING_REVIEWER_PROFILES", "") == "1":
            # Explicit test-only compatibility path.
            return RuntimeProfile()
        raise RuntimeError(f"missing reviewer profiles: {profiles_path}")

    try:
        cfg = load_reviewer_profiles(profiles_path)
    except ReviewerProfilesError as exc:
        raise RuntimeError(f"reviewer profiles error: {exc}") from exc
    return cfg.merged_for_perspective(perspective)


def resolve_resource_paths(base: Path, values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        p = Path(value)
        if not p.is_absolute():
            p = base / p
        out.append(str(p.resolve()))
    return out


def select_pool_model(
    *,
    reviewer_name: str,
    requested_wave: str,
    requested_tier: str,
    model_wave_pools: dict[str, list[str]],
    model_tiers: dict[str, list[str]],
    model_pool: list[str],
) -> str:
    if requested_wave:
        wave_pool = model_wave_pools.get(requested_wave, [])
        if wave_pool:
            selected = random.choice(wave_pool)
            print(
                f"::notice::Selected random model from {requested_wave} wave pool for {reviewer_name}: {selected}"
            )
            return selected

    candidate_tiers = [requested_tier]
    if requested_tier != "standard":
        candidate_tiers.append("standard")
    candidate_tiers.append("")

    selected_pool: list[str] = []
    found_tier = ""

    for candidate in candidate_tiers:
        pool = model_tiers.get(candidate, []) if candidate else model_pool
        if pool:
            selected_pool = pool
            found_tier = candidate
            break

    if found_tier:
        if found_tier == requested_tier:
            print(f"::notice::Selected random model from {found_tier} tier pool for {reviewer_name}.")
        elif found_tier == "standard":
            print(
                "::notice::"
                f"Tier '{requested_tier}' had no models; falling back to standard tier pool for {reviewer_name}."
            )
        else:
            print(f"::notice::Selected random model from unscoped pool for {reviewer_name}.")
    else:
        print(f"::notice::Selected random model from unscoped pool for {reviewer_name}.")

    if not selected_pool:
        return ""

    selected = random.choice(selected_pool)
    print(f"::notice::Selected random model from pool: {selected}")
    return selected


def classify_api_error_text(text: str) -> str:
    lower = text.lower()
    if re.search(r"incorrect_api_key|invalid_api_key|invalid.api.key|authentication|unauthorized|401|missing authentication header", lower):
        return "API_KEY_INVALID"
    if re.search(r"exceeded_current_quota|insufficient_quota|insufficient.credits|payment.required|quota.exceeded|credits.depleted|credits.exhausted|402", lower):
        return "API_CREDITS_DEPLETED"
    return "API_ERROR"


def redact_runtime_error(text: str) -> str:
    redacted = text
    patterns = [
        (r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+", r"\1<redacted>"),
        (r"(?i)((?:api|access|secret|auth)[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(token\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def write_api_error_marker(
    *,
    stdout_file: Path,
    stderr_file: Path,
    models: list[str],
) -> None:
    error_msg = f"{read_text(stdout_file) if stdout_file.exists() else ''}\n{read_text(stderr_file) if stderr_file.exists() else ''}"
    sanitized_error = redact_runtime_error(error_msg)
    error_type = classify_api_error_text(sanitized_error)
    models_tried = " ".join(models)
    marker = (
        f"API Error: {error_type}\n\n"
        "The API provider returned an error that prevents the review from completing:\n\n"
        f"{sanitized_error.strip()}\n\n"
        f"Models tried: {models_tried}\n"
        "Please check your API key and quota settings.\n"
    )
    write_text(stdout_file, marker)


def render_fast_path_prompt(
    *,
    template_path: Path,
    perspective: str,
    reviewer_name: str,
    diff_content: str,
    output_path: Path,
) -> None:
    template = read_text(template_path)
    rendered = (
        template.replace("{{PERSPECTIVE}}", perspective)
        .replace("{{REVIEWER_NAME}}", reviewer_name)
        .replace("{{DIFF_CONTENT}}", diff_content)
    )
    write_text(output_path, rendered)


def print_tail(path: Path, *, lines: int = 40) -> None:
    print("--- output (last 40 lines) ---")
    if not path.exists():
        print("(missing parse input file)")
        print("--- end output ---")
        return
    content_lines = read_text(path).splitlines()
    for line in content_lines[-lines:]:
        print(line)
    print("--- end output ---")


def try_structured_extraction(
    *,
    cerberus_root: Path,
    scratchpad: Path,
    stdout_file: Path,
    perspective: str,
    model_used: str,
    output_file: Path,
) -> bool:
    """Call extract-verdict.py to pull structured JSON from the scratchpad.

    Returns True and writes to output_file on success; False otherwise.
    Falls back to stdout_file if scratchpad is empty.
    """
    extract_script = cerberus_root / "scripts" / "extract-verdict.py"
    if not extract_script.exists():
        return False

    source: Path | None = None
    if scratchpad.exists() and scratchpad.stat().st_size > 0:
        source = scratchpad
    elif stdout_file.exists() and stdout_file.stat().st_size > 0:
        source = stdout_file

    if source is None:
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(extract_script), str(source), perspective, model_used],
            capture_output=True,
            text=True,
            timeout=90,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        print("Structured extraction timed out; falling back to fenced-block parsing.")
        return False
    except Exception as exc:
        print(f"Structured extraction subprocess error: {exc}")
        return False

    if result.returncode != 0:
        stderr_snippet = result.stderr.strip()[:300]
        print(f"Structured extraction failed (exit {result.returncode}): {stderr_snippet}")
        return False

    try:
        json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"Structured extraction: invalid JSON output: {exc}")
        return False

    write_text(output_file, result.stdout)
    print("Structured extraction: success — using structured verdict.")
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 1 or not argv[0].strip():
        eprint("usage: run-reviewer.sh <perspective>")
        return 2

    perspective = argv[0].strip()
    if "/" in perspective or ".." in perspective:
        eprint(f"invalid perspective: {perspective}")
        return 2

    cerberus_root_raw = os.environ.get("CERBERUS_ROOT", "").strip()
    if not cerberus_root_raw:
        eprint("CERBERUS_ROOT not set")
        return 2
    cerberus_root = Path(cerberus_root_raw).resolve()

    cerberus_tmp_raw = os.environ.get("CERBERUS_TMP", "").strip()
    if not cerberus_tmp_raw:
        cerberus_tmp = Path(tempfile.mkdtemp(prefix="cerberus."))
        os.environ["CERBERUS_TMP"] = str(cerberus_tmp)
    else:
        cerberus_tmp = Path(cerberus_tmp_raw)
        cerberus_tmp.mkdir(parents=True, exist_ok=True)

    try:
        cerberus_tmp.chmod(0o700)
    except OSError:
        pass

    config_file = cerberus_root / "defaults" / "config.yml"
    agent_file = cerberus_root / ".opencode" / "agents" / f"{perspective}.md"

    if not agent_file.is_file():
        eprint(f"missing agent file: {agent_file}")
        return 2

    try:
        defaults_cfg = load_defaults_config(config_file)
    except ConfigError as exc:
        eprint(f"defaults config error: {exc}")
        return 2

    reviewer = defaults_cfg.reviewer_for_perspective(perspective)
    if reviewer is None:
        eprint(f"unknown perspective in config: {perspective}")
        return 2

    reviewer_name = reviewer.name
    reviewer_desc = reviewer.description or ""

    reviewer_name_file = cerberus_tmp / f"{perspective}-reviewer-name"
    write_text(reviewer_name_file, reviewer_name)
    if reviewer_desc:
        write_text(cerberus_tmp / f"{perspective}-reviewer-desc", reviewer_desc)

    try:
        profile = resolve_profile(cerberus_root, perspective)
    except RuntimeError as exc:
        eprint(str(exc))
        return 2

    tools = profile.tools or ["read", "grep", "find", "ls", "write", "edit"]
    extensions = resolve_resource_paths(cerberus_root, profile.extensions)
    skills = resolve_resource_paths(cerberus_root, profile.skills)

    profile_provider = sanitize_model(profile.provider) or "openrouter"
    profile_model = sanitize_model(profile.model)

    requested_tier = normalize_tier(os.environ.get("MODEL_TIER"))
    requested_wave = normalize_wave(os.environ.get("MODEL_WAVE"))

    reviewer_model_raw = sanitize_model(reviewer.model)
    config_default_model = sanitize_model(defaults_cfg.model.default)

    if profile_model:
        if profile_model == "pool":
            selected = select_pool_model(
                reviewer_name=reviewer_name,
                requested_wave=requested_wave,
                requested_tier=requested_tier,
                model_wave_pools=defaults_cfg.model.wave_pools,
                model_tiers=defaults_cfg.model.tiers,
                model_pool=defaults_cfg.model.pool,
            )
            profile_model = selected
        reviewer_model_raw = profile_model or reviewer_model_raw
    elif reviewer_model_raw == "pool":
        selected = select_pool_model(
            reviewer_name=reviewer_name,
            requested_wave=requested_wave,
            requested_tier=requested_tier,
            model_wave_pools=defaults_cfg.model.wave_pools,
            model_tiers=defaults_cfg.model.tiers,
            model_pool=defaults_cfg.model.pool,
        )
        if selected:
            reviewer_model_raw = selected
        else:
            print("::warning::Reviewer uses 'pool' but no pool defined. Falling back to default.")
            reviewer_model_raw = ""

    configured_model = BASE_DEFAULT_MODEL
    if config_default_model:
        configured_model = config_default_model
    if reviewer_model_raw:
        configured_model = reviewer_model_raw

    input_model = sanitize_model(os.environ.get("PI_MODEL") or os.environ.get("OPENCODE_MODEL"))
    primary_model = input_model or configured_model

    write_text(cerberus_tmp / f"{perspective}-configured-model", configured_model)
    write_text(cerberus_tmp / f"{perspective}-primary-model", primary_model)

    if input_model:
        if primary_model != configured_model:
            print(
                "::warning::"
                f"Model override active for {reviewer_name} ({perspective}): using '{primary_model}' "
                f"(configured: '{configured_model}'). Remove the 'model' input to use per-reviewer defaults."
            )
        else:
            print(
                "::notice::"
                f"Model override set for {reviewer_name} ({perspective}) but matches configured model ('{configured_model}'). "
                "Remove 'model' to stay auto-updated as Cerberus defaults evolve."
            )

    models = [primary_model]
    fallback_models_raw = os.environ.get("CERBERUS_FALLBACK_MODELS", "")
    if fallback_models_raw:
        for item in fallback_models_raw.split(","):
            m = sanitize_model(item)
            if m:
                models.append(m)

    provider_key_var, api_key = resolve_api_key_for_provider(profile_provider, os.environ)
    if not api_key:
        eprint(f"missing {provider_key_var}")
        return 2

    diff_file_raw = os.environ.get("GH_DIFF_FILE", "").strip()
    diff_from_env = os.environ.get("GH_DIFF", "")
    if diff_file_raw and Path(diff_file_raw).is_file():
        diff_file = Path(diff_file_raw)
    elif diff_from_env:
        diff_file = cerberus_tmp / "pr.diff"
        write_text(diff_file, diff_from_env)
    else:
        eprint("missing diff input (GH_DIFF or GH_DIFF_FILE)")
        return 2

    prompt_file = cerberus_tmp / f"{perspective}-review-prompt.md"
    try:
        render_review_prompt_file(
            cerberus_root=cerberus_root,
            env=os.environ,
            diff_file=str(diff_file),
            perspective=perspective,
            output_path=prompt_file,
        )
    except (OSError, ValueError) as exc:
        eprint(f"render-review-prompt: {exc}")
        return 2

    # Build trusted system prompt from perspective prompt body.
    system_prompt_file = cerberus_tmp / f"{perspective}-system-prompt.md"
    prompt_body = strip_frontmatter(read_text(agent_file)).strip()
    if not prompt_body:
        eprint(f"invalid agent prompt body: {agent_file}")
        return 2
    write_text(system_prompt_file, prompt_body)

    isolated_home = Path(tempfile.mkdtemp(prefix=f"cerberus-home-{perspective}.", dir=str(cerberus_tmp)))
    (isolated_home / ".config").mkdir(parents=True, exist_ok=True)
    (isolated_home / ".local" / "share").mkdir(parents=True, exist_ok=True)
    (isolated_home / "tmp").mkdir(parents=True, exist_ok=True)
    agent_dir = isolated_home / "pi-agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    review_timeout = parse_positive_int(os.environ.get("REVIEW_TIMEOUT"), profile.timeout or 600)
    max_steps = parse_positive_int(os.environ.get("OPENCODE_MAX_STEPS"), profile.max_steps or 25)

    telemetry_file = cerberus_tmp / f"{perspective}-runtime-telemetry.ndjson"

    stdout_file = cerberus_tmp / f"{perspective}-output.txt"
    stderr_file = cerberus_tmp / f"{perspective}-stderr.log"
    scratchpad = cerberus_tmp / f"{perspective}-review.md"
    structured_verdict_file = cerberus_tmp / f"{perspective}-structured-verdict.json"

    def run_attempt(
        *,
        model: str,
        timeout_seconds: int,
        attempt_prompt_file: Path,
        attempt_max_steps: int | None = None,
    ):
        req = RuntimeAttemptRequest(
            perspective=perspective,
            provider=profile_provider,
            model=model,
            prompt_file=attempt_prompt_file,
            system_prompt_file=system_prompt_file,
            timeout_seconds=timeout_seconds,
            tools=tools,
            extensions=extensions,
            skills=skills,
            thinking_level=profile.thinking_level,
            api_key=api_key,
            agent_dir=agent_dir,
            isolated_home=isolated_home,
            max_steps=attempt_max_steps if attempt_max_steps is not None else max_steps,
            trusted_system_prompt_file=system_prompt_file,
            telemetry_file=telemetry_file,
            prompt_capture_path=os.environ.get("CERBERUS_PROMPT_CAPTURE_PATH"),
        )
        result = run_pi_attempt(req)
        write_text(stdout_file, result.stdout)
        write_text(stderr_file, result.stderr)
        return result

    print(f"Running reviewer: {reviewer_name} ({perspective})")

    fast_path_budget = review_timeout // 5
    if os.environ.get("CERBERUS_TEST_FAST_PATH", "") == "1":
        if review_timeout > 1 and fast_path_budget <= 0:
            fast_path_budget = 1
        if fast_path_budget >= review_timeout:
            fast_path_budget = max(review_timeout - 1, 0)
    else:
        if fast_path_budget > 120:
            fast_path_budget = 120
        if fast_path_budget < 60:
            fast_path_budget = 0
    primary_timeout = review_timeout - fast_path_budget if fast_path_budget > 0 else review_timeout

    model_used = models[0]
    fallback_triggered = False
    model_index = 0
    exit_code = 0
    detected_error_type = "none"
    detected_error_class = "none"
    detected_retry_after: int | None = None

    review_start_time = time.time()
    run_completed = False

    while model_index < len(models):
        model = models[model_index]
        if model_index > 0:
            print(f"Falling back to model: {model} (fallback {model_index}/{len(models)})")
            fallback_triggered = True
        model_used = model

        retry_count = 0
        advance_to_next_model = False

        while True:
            remaining_budget = get_remaining_timeout(review_start_time, primary_timeout)
            if remaining_budget == 0:
                print("Timeout budget exhausted before attempt — treating as timeout.")
                exit_code = 124
                run_completed = True
                break

            result = run_attempt(model=model, timeout_seconds=remaining_budget, attempt_prompt_file=prompt_file)
            exit_code = result.exit_code

            output_size = stdout_file.stat().st_size if stdout_file.exists() else 0
            scratchpad_size = scratchpad.stat().st_size if scratchpad.exists() else 0
            print(
                f"pi exit={exit_code} stdout={output_size} bytes scratchpad={scratchpad_size} bytes "
                f"model={model} (attempt {retry_count + 1}/{MAX_RETRIES + 1})"
            )

            if exit_code == 0:
                if output_size > 0 or scratchpad_size > 0:
                    run_completed = True
                    break
                print("pi exited 0 but produced no output. Treating as transient failure.")
                detected_error_type = "transient"
                detected_error_class = "empty_output"
                detected_retry_after = None
                if retry_count < MAX_RETRIES:
                    retry_count += 1
                    wait_seconds = default_backoff_seconds(retry_count)
                    print(f"Retrying empty output (attempt {retry_count}/{MAX_RETRIES}); wait={wait_seconds}s")
                    maybe_sleep(wait_seconds)
                    continue
                advance_to_next_model = True
                break

            detected_error_type = result.error_type
            detected_error_class = result.error_class
            detected_retry_after = result.retry_after_seconds

            if exit_code == 124:
                run_completed = True
                break

            if detected_error_type == "transient" and retry_count < MAX_RETRIES:
                retry_count += 1
                wait_seconds = default_backoff_seconds(retry_count)
                if detected_error_class == "rate_limit" and detected_retry_after and detected_retry_after > 0:
                    wait_seconds = detected_retry_after
                print(
                    "Retrying after transient error "
                    f"(class={detected_error_class}) attempt {retry_count}/{MAX_RETRIES}; wait={wait_seconds}s"
                )
                maybe_sleep(wait_seconds)
                continue

            if detected_error_type == "transient":
                advance_to_next_model = True
                break

            if detected_error_class == "auth_or_quota":
                print("Permanent API error detected (auth/quota). Writing error verdict.")
                run_completed = True
                break

            if detected_error_type == "permanent":
                advance_to_next_model = True
                break

            print(f"Unknown error type (exit={exit_code}). Trying next model if available...")
            advance_to_next_model = True
            break

        if run_completed:
            break

        if advance_to_next_model and model_index + 1 < len(models):
            print(f"Model {model} exhausted retries (class={detected_error_class}). Trying next fallback...")
            model_index += 1
            continue

        break

    # Attempt structured extraction after successful Pi run.
    # This replaces fragile regex-based JSON block parsing with schema-enforced structured output.
    if exit_code == 0:
        try_structured_extraction(
            cerberus_root=cerberus_root,
            scratchpad=scratchpad,
            stdout_file=stdout_file,
            perspective=perspective,
            model_used=model_used,
            output_file=structured_verdict_file,
        )

    parse_failure_retries = 0
    parse_failure_models_attempted: list[str] = []

    if (
        exit_code == 0
        and not structured_verdict_file.exists()
        and not has_valid_json_block(stdout_file)
        and not has_valid_json_block(scratchpad)
    ):
        print("Parse failure detected: no valid JSON block in output. Attempting recovery retries...")

        for pf_model in models:
            if has_valid_json_block(stdout_file) or has_valid_json_block(scratchpad):
                print("Parse recovery: valid JSON found after retry.")
                break

            remaining = get_remaining_timeout(review_start_time, primary_timeout)
            if remaining == 0:
                print("Parse recovery: timeout budget exhausted, skipping remaining models.")
                break

            parse_failure_models_attempted.append(pf_model)
            parse_failure_retries += 1
            print(f"Parse recovery retry {parse_failure_retries}: model={pf_model}")

            pf_result = run_attempt(model=pf_model, timeout_seconds=remaining, attempt_prompt_file=prompt_file)
            pf_exit = pf_result.exit_code
            output_size = stdout_file.stat().st_size if stdout_file.exists() else 0
            scratchpad_size = scratchpad.stat().st_size if scratchpad.exists() else 0
            print(
                f"Parse recovery exit={pf_exit} stdout={output_size} bytes scratchpad={scratchpad_size} bytes "
                f"model={pf_model}"
            )

            if pf_exit == 0 and (output_size > 0 or scratchpad_size > 0):
                if has_valid_json_block(stdout_file) or has_valid_json_block(scratchpad):
                    print("Parse recovery successful: valid JSON block found.")
                    model_used = pf_model
                    exit_code = 0
                    break

        if not has_valid_json_block(stdout_file) and not has_valid_json_block(scratchpad):
            print(
                "Parse recovery failed: "
                f"no valid JSON after {parse_failure_retries} retries across {len(parse_failure_models_attempted)} models."
            )
            if parse_failure_models_attempted:
                write_text(
                    cerberus_tmp / f"{perspective}-parse-failure-models.txt",
                    "\n".join(parse_failure_models_attempted) + "\n",
                )
                write_text(
                    cerberus_tmp / f"{perspective}-parse-failure-retries.txt",
                    str(parse_failure_retries),
                )

    print(f"model_used={model_used}")
    if fallback_triggered:
        print(f"::notice::Review used fallback model: {model_used} (primary: {models[0]})")

    write_text(cerberus_tmp / f"{perspective}-model-used", model_used)

    if exit_code != 0:
        error_type, _error_class, _ = classify_runtime_error(
            stdout=read_text(stdout_file) if stdout_file.exists() else "",
            stderr=read_text(stderr_file) if stderr_file.exists() else "",
            exit_code=exit_code,
        )
        if error_type in {"permanent", "transient"}:
            print(f"{error_type.capitalize()} API/runtime error detected. Writing error verdict.")
            write_api_error_marker(stdout_file=stdout_file, stderr_file=stderr_file, models=models)
            exit_code = 0

    if exit_code not in {0, 124}:
        eprint("--- stderr ---")
        if stderr_file.exists():
            eprint(read_text(stderr_file))
        if (scratchpad.exists() and scratchpad.stat().st_size > 0) or (stdout_file.exists() and stdout_file.stat().st_size > 0):
            print("Unknown error but output exists — delegating to parser.")
            exit_code = 0

    timeout_marker = cerberus_tmp / f"{perspective}-timeout-marker.txt"
    parse_input: Path

    if exit_code == 124:
        print(f"::warning::{reviewer_name} ({perspective}) timed out after {review_timeout}s")

        if structured_verdict_file.exists() and structured_verdict_file.stat().st_size > 0:
            parse_input = structured_verdict_file
            print("parse-input: structured verdict (timeout, extracted before deadline)")
        elif has_valid_json_block(scratchpad):
            parse_input = scratchpad
            print("parse-input: scratchpad (timeout, but has JSON block)")
        elif has_valid_json_block(stdout_file):
            parse_input = stdout_file
            print("parse-input: stdout (timeout, but has JSON block)")
        elif scratchpad.exists() and scratchpad.stat().st_size > 0:
            parse_input = scratchpad
            print("parse-input: scratchpad (timeout, partial review)")
        elif stdout_file.exists() and stdout_file.stat().st_size > 0:
            parse_input = stdout_file
            print("parse-input: stdout (timeout, partial review)")
        else:
            diff_files = extract_diff_files(diff_file)
            fast_path_attempted = "no"

            if fast_path_budget > 0:
                fast_template = cerberus_root / "templates" / "fast-path-prompt.md"
                if fast_template.exists():
                    fast_path_attempted = "yes"
                    print(
                        "Primary review timed out with no output. "
                        f"Running fast-path fallback ({fast_path_budget}s)..."
                    )
                    diff_content = diff_file.read_bytes()[:51200].decode("utf-8", errors="replace")
                    diff_byte_count = diff_file.stat().st_size
                    if diff_byte_count > 51200:
                        diff_content += f"\n... (truncated, {diff_byte_count} bytes total)"

                    fast_prompt_file = cerberus_tmp / f"{perspective}-fast-path-prompt.md"
                    fast_output_file = cerberus_tmp / f"{perspective}-fast-path-output.txt"
                    fast_stderr_file = cerberus_tmp / f"{perspective}-fast-path-stderr.log"

                    render_fast_path_prompt(
                        template_path=fast_template,
                        perspective=perspective,
                        reviewer_name=reviewer_name,
                        diff_content=diff_content,
                        output_path=fast_prompt_file,
                    )

                    fp_result = run_attempt(
                        model=model_used,
                        timeout_seconds=fast_path_budget,
                        attempt_prompt_file=fast_prompt_file,
                        attempt_max_steps=1,
                    )
                    write_text(fast_output_file, fp_result.stdout)
                    write_text(fast_stderr_file, fp_result.stderr)

                    fp_size = fast_output_file.stat().st_size if fast_output_file.exists() else 0
                    print(f"fast-path exit={fp_result.exit_code} stdout={fp_size} bytes")

                    if fp_result.exit_code == 0 and has_valid_json_block(fast_output_file):
                        parse_input = fast_output_file
                        print("parse-input: fast-path output (has JSON block)")
                    else:
                        parse_input = timeout_marker
                else:
                    parse_input = timeout_marker
            else:
                parse_input = timeout_marker

            if parse_input == timeout_marker:
                diff_files_text = "\n".join(diff_files) if diff_files else "(none)"
                marker = (
                    f"Review Timeout: timeout after {review_timeout}s\n"
                    f"{reviewer_name} ({perspective}) exceeded the configured timeout.\n"
                    f"Fast-path: {fast_path_attempted}\n"
                    f"Files in diff:\n{diff_files_text}\n"
                    "Next steps: Increase timeout, reduce diff size, or check model provider status.\n"
                )
                write_text(timeout_marker, marker)
                print("parse-input: timeout marker (no output to salvage)")

        exit_code = 0
    else:
        parse_input = stdout_file
        if structured_verdict_file.exists() and structured_verdict_file.stat().st_size > 0:
            parse_input = structured_verdict_file
            print("parse-input: structured verdict (extracted from scratchpad)")
        elif has_valid_json_block(scratchpad):
            parse_input = scratchpad
            print("parse-input: scratchpad (has JSON block)")
        elif has_valid_json_block(stdout_file):
            parse_input = stdout_file
            print("parse-input: stdout (has JSON block)")
        elif scratchpad.exists() and scratchpad.stat().st_size > 0:
            parse_input = scratchpad
            print("parse-input: scratchpad (partial, no JSON block)")
        else:
            print("parse-input: stdout (fallback)")

    write_text(cerberus_tmp / f"{perspective}-parse-input", str(parse_input))
    print_tail(parse_input)

    write_text(cerberus_tmp / f"{perspective}-exitcode", str(exit_code))
    return exit_code

    
if __name__ == "__main__":
    try:
        rc = main(sys.argv[1:])
    finally:
        # Best-effort cleanup of isolated HOME if requested by caller env.
        # CERBERUS_TMP lifecycle is managed by action.yml.
        pass
    raise SystemExit(rc)
