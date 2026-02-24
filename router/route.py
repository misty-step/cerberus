#!/usr/bin/env python3
"""Route a Cerberus reviewer panel for a PR diff."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib import error, request

import yaml

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ROUTER_MODEL = "google/gemini-3-flash-preview"
OUTPUT_PATH = "/tmp/router-output.json"
DEFAULT_PANEL = ["correctness", "architecture", "security", "maintainability", "testing"]
MODEL_TIER_FLASH = "flash"
MODEL_TIER_STANDARD = "standard"
MODEL_TIER_PRO = "pro"

DOC_EXTENSIONS = {
    ".md",
    ".mdx",
    ".rst",
    ".txt",
    ".adoc",
    ".asciidoc",
    ".org",
}

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".sql",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
}


def warn(message: str) -> None:
    """Print warning in GitHub Actions format."""
    print(f"::warning::{message}")


def as_int(value: Any, default: int) -> int:
    """Best-effort int parse with fallback."""
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def split_description(value: Any) -> tuple[str, str]:
    """Split description into role and focus."""
    text = str(value or "").strip()
    if not text:
        return ("", "")
    if "—" in text:
        left, right = text.split("—", 1)
        return (left.strip(), right.strip())
    if " - " in text:
        left, right = text.split(" - ", 1)
        return (left.strip(), right.strip())
    return (text, "")


def clean_token(token: str) -> str:
    """Normalize reviewer token."""
    return token.strip().strip('"').strip("'").lower()


def unique_ordered(items: list[str]) -> list[str]:
    """Deduplicate while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def is_doc_path(path: str) -> bool:
    """Return True if this file path looks like docs."""
    normalized = path.lower().strip("/")
    name = Path(normalized).name
    ext = Path(normalized).suffix.lower()
    if ext in DOC_EXTENSIONS:
        return True
    if normalized.startswith(("docs/", "doc/")):
        return True
    if name in {"readme", "readme.md", "changelog.md", "license", "contributing.md"}:
        return True
    return False


def is_test_path(path: str) -> bool:
    """Return True if this file path looks like tests."""
    normalized = path.lower().strip("/")
    name = Path(normalized).name
    if "/test/" in f"/{normalized}/" or "/tests/" in f"/{normalized}/":
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    if normalized.startswith(("test/", "tests/")):
        return True
    return False


def classify_file(path: str) -> tuple[bool, bool, bool]:
    """Classify changed file into doc/test/code buckets."""
    doc = is_doc_path(path)
    test = is_test_path(path)
    ext = Path(path).suffix.lower()
    if doc or test:
        return (doc, test, False)
    if ext in CODE_EXTENSIONS:
        return (False, False, True)
    if ext == "":
        # Conservative: extensionless files are treated as code/config.
        return (False, False, True)
    # Unknown extension: still count as code-like for guard safety.
    return (False, False, True)


def load_config(cerberus_root: str) -> dict[str, Any]:
    """Load defaults/config.yml and normalize routing metadata."""
    config_path = Path(cerberus_root) / "defaults" / "config.yml"
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    reviewers = config.get("reviewers", []) or []
    bench: list[dict[str, str]] = []
    name_to_perspective: dict[str, str] = {}
    perspectives: list[str] = []
    for reviewer in reviewers:
        name = clean_token(str(reviewer.get("name", "")))
        perspective = clean_token(str(reviewer.get("perspective", "")))
        if not name or not perspective:
            continue
        role, focus = split_description(reviewer.get("description"))
        bench.append(
            {
                "name": name,
                "perspective": perspective,
                "description": str(reviewer.get("description", "")).strip(),
                "role": role,
                "focus": focus or str(reviewer.get("description", "")).strip(),
            }
        )
        name_to_perspective[name] = perspective
        perspectives.append(perspective)

    routing = config.get("routing", {}) or {}
    always_names = [clean_token(str(item)) for item in (routing.get("always_include") or ["trace"])]
    guard_names = [clean_token(str(item)) for item in (routing.get("include_if_code_changed") or ["guard"])]
    fallback_names = [clean_token(str(item)) for item in (routing.get("fallback_panel") or [])]

    return {
        "bench": bench,
        "name_to_perspective": name_to_perspective,
        "perspectives": unique_ordered(perspectives),
        "default_panel_size": as_int(routing.get("panel_size"), 5),
        "always_names": always_names,
        "guard_names": guard_names,
        "fallback_names": fallback_names,
    }


def resolve_tokens(tokens: list[str], cfg: dict[str, Any]) -> list[str]:
    """Resolve reviewer names/perspectives to canonical perspective strings."""
    out: list[str] = []
    valid = set(cfg["perspectives"])
    by_name = cfg["name_to_perspective"]
    for token in tokens:
        t = clean_token(token)
        if not t:
            continue
        if t in by_name:
            out.append(by_name[t])
        elif t in valid:
            out.append(t)
    return unique_ordered(out)


def required_perspectives(cfg: dict[str, Any], code_changed: bool) -> list[str]:
    """Return required perspectives based on config and changed file types."""
    required = resolve_tokens(cfg["always_names"], cfg)
    if code_changed:
        required.extend(resolve_tokens(cfg["guard_names"], cfg))
    return unique_ordered(required)


def build_fallback_panel(cfg: dict[str, Any], panel_size: int, code_changed: bool) -> list[str]:
    """Build safe fallback panel from config."""
    max_size = min(max(panel_size, 1), len(cfg["perspectives"]) or panel_size)
    required = required_perspectives(cfg, code_changed)
    panel = required.copy()
    panel.extend(resolve_tokens(cfg["fallback_names"], cfg))
    panel.extend(cfg["perspectives"])
    panel = unique_ordered(panel)
    if not panel:
        panel = DEFAULT_PANEL[:]
    return panel[:max_size]


def parse_diff(diff_path: str) -> dict[str, Any]:
    """Parse unified diff into file-level stats and summary metadata."""
    path = Path(diff_path)
    if not path.exists():
        warn(f"Diff file not found: {diff_path}")
        return {
            "files": [],
            "total_additions": 0,
            "total_deletions": 0,
            "total_changed_lines": 0,
            "total_files": 0,
            "extensions": {},
            "doc_files": 0,
            "test_files": 0,
            "code_files": 0,
            "code_changed": False,
        }

    files: dict[str, dict[str, Any]] = {}
    current: str | None = None
    total_additions = 0
    total_deletions = 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")

            if line.startswith("diff --git "):
                parts = line.split()
                if len(parts) >= 4:
                    b_path = parts[3]
                    if b_path.startswith("b/"):
                        b_path = b_path[2:]
                    current = b_path
                    files.setdefault(
                        current,
                        {
                            "path": current,
                            "additions": 0,
                            "deletions": 0,
                        },
                    )
                continue

            if line.startswith("rename to ") and current:
                renamed = line[len("rename to ") :].strip()
                if renamed:
                    record = files.pop(current, {"path": renamed, "additions": 0, "deletions": 0})
                    record["path"] = renamed
                    files[renamed] = record
                    current = renamed
                continue

            if line.startswith("+++ ") and current:
                plus_path = line[4:].strip()
                if plus_path.startswith("b/"):
                    candidate = plus_path[2:]
                    if candidate and candidate != current:
                        record = files.pop(current, {"path": candidate, "additions": 0, "deletions": 0})
                        record["path"] = candidate
                        files[candidate] = record
                        current = candidate
                continue

            if not current:
                continue

            if line.startswith("+") and not line.startswith("+++"):
                files[current]["additions"] += 1
                total_additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                files[current]["deletions"] += 1
                total_deletions += 1

    rows: list[dict[str, Any]] = []
    ext_counts: Counter[str] = Counter()
    doc_files = 0
    test_files = 0
    code_files = 0

    for file_path in sorted(files):
        record = files[file_path]
        ext = Path(file_path).suffix.lower() or "(none)"
        is_doc, is_test, is_code = classify_file(file_path)
        record["extension"] = ext
        record["is_doc"] = is_doc
        record["is_test"] = is_test
        record["is_code"] = is_code
        rows.append(record)
        ext_counts[ext] += 1
        if is_doc:
            doc_files += 1
        elif is_test:
            test_files += 1
        elif is_code:
            code_files += 1

    return {
        "files": rows,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "total_changed_lines": total_additions + total_deletions,
        "total_files": len(rows),
        "extensions": dict(ext_counts.most_common()),
        "doc_files": doc_files,
        "test_files": test_files,
        "code_files": code_files,
        "code_changed": code_files > 0,
    }


def classify_model_tier(summary: dict[str, Any]) -> str:
    """Classify PR complexity for model selection."""
    total_lines = int(summary.get("total_changed_lines", 0))
    code_files = int(summary.get("code_files", 0))
    test_files = int(summary.get("test_files", 0))
    doc_files = int(summary.get("doc_files", 0))

    security_hints = {
        "auth",
        "security",
        "permission",
        "permissions",
        "oauth",
        "jwt",
        "api",
        "route",
        "router",
    }

    has_security_hint = any(
        any(hint in file_path.lower() for hint in security_hints)
        for file_path in (item.get("path", "") for item in summary.get("files", []))
    )

    if total_lines <= 50 and code_files == 0 and (test_files + doc_files) > 0:
        return MODEL_TIER_FLASH
    if total_lines >= 300 or has_security_hint:
        return MODEL_TIER_PRO
    return MODEL_TIER_STANDARD


def build_prompt(cfg: dict[str, Any], summary: dict[str, Any], panel_size: int) -> str:
    """Build structured router prompt for Gemini."""
    required = required_perspectives(cfg, summary["code_changed"])
    required_text = ", ".join(required) if required else "(none)"
    ext_text = ", ".join(f"{k}:{v}" for k, v in summary["extensions"].items()) or "(none)"
    repo = os.getenv("GITHUB_REPOSITORY", "unknown")
    ref = os.getenv("GITHUB_REF_NAME", "unknown")
    event = os.getenv("GITHUB_EVENT_NAME", "unknown")

    bench_lines = [
        "| Codename | Perspective | Focus |",
        "|----------|-------------|-------|",
    ]
    for item in cfg["bench"]:
        focus = item["focus"] or item["description"] or item["perspective"]
        bench_lines.append(f"| {item['name']} | {item['perspective']} | {focus} |")

    changed_files = summary["files"][:250]
    file_lines = []
    for item in changed_files:
        tags = []
        if item["is_code"]:
            tags.append("code")
        if item["is_test"]:
            tags.append("test")
        if item["is_doc"]:
            tags.append("doc")
        tag_text = ",".join(tags) if tags else "unknown"
        file_lines.append(
            f"- {item['path']} (+{item['additions']}, -{item['deletions']}) [ext={item['extension']} type={tag_text}]"
        )
    if not file_lines:
        file_lines.append("- (no changed files parsed)")

    return "\n".join(
        [
            f"You are a code review router for Cerberus. Select exactly {panel_size} reviewers from the bench below that are most relevant to this PR.",
            "",
            "## Bench",
            *bench_lines,
            "",
            "## Constraints",
            f"- Select EXACTLY {panel_size} reviewers",
            f"- Required perspectives for this PR: {required_text}",
            "- The required perspectives MUST be included in your selection",
            "- Choose remaining slots by relevance to the changed files",
            "- Return perspectives only (not codenames)",
            "",
            "## PR Metadata",
            f"- Repository: {repo}",
            f"- Ref: {ref}",
            f"- Event: {event}",
            f"- Files changed: {summary['total_files']}",
            f"- Lines added: {summary['total_additions']}",
            f"- Lines removed: {summary['total_deletions']}",
            f"- Total changed lines: {summary['total_changed_lines']}",
            f"- Code files: {summary['code_files']} | Test files: {summary['test_files']} | Doc files: {summary['doc_files']}",
            f"- Extension histogram: {ext_text}",
            "",
            "## Changed Files",
            *file_lines,
            "",
            "## Output",
            f'Respond with ONLY a JSON array of exactly {panel_size} perspective strings.',
            'Example: ["correctness","security","architecture","testing","maintainability"]',
        ]
    )


def call_router(api_key: str, prompt: str, panel_size: int) -> tuple[str | None, str]:
    """Call OpenRouter and return raw model content + model name."""
    payload = {
        "model": ROUTER_MODEL,
        "temperature": 0.1,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": "You route specialist reviewers to pull requests. Follow constraints exactly."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "cerberus_panel",
                "strict": True,
                "schema": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": panel_size,
                    "maxItems": panel_size,
                },
            },
        },
    }

    req = request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "cerberus-router/1.0",
            "HTTP-Referer": "https://github.com/misty-step/cerberus",
            "X-Title": "Cerberus Router",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        warn(f"Router API HTTP error {exc.code}: {detail[:400]}")
        return (None, ROUTER_MODEL)
    except Exception as exc:
        warn(f"Router API request failed: {exc}")
        return (None, ROUTER_MODEL)

    model_used = str(body.get("model") or ROUTER_MODEL)
    choices = body.get("choices") or []
    if not choices:
        warn("Router API returned no choices")
        return (None, model_used)

    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                text_parts.append(item)
        content = "\n".join(part for part in text_parts if part)
    if not isinstance(content, str):
        warn("Router API response content was not text")
        return (None, model_used)
    return (content.strip(), model_used)


def parse_panel_from_text(raw: str | None) -> list[str]:
    """Extract panel array from raw model text."""
    if not raw:
        return []

    candidates = [raw.strip()]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(chunk.strip() for chunk in fenced if chunk.strip())

    bracket_match = re.search(r"\[[\s\S]*\]", raw)
    if bracket_match:
        candidates.append(bracket_match.group(0).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        if isinstance(parsed, dict) and isinstance(parsed.get("panel"), list):
            return [str(item) for item in parsed["panel"]]
    return []


def validate_panel(panel: list[str], cfg: dict[str, Any], panel_size: int, code_changed: bool) -> list[str]:
    """Validate and normalize panel from model output."""
    normalized = resolve_tokens(panel, cfg)
    if len(normalized) != panel_size:
        return []

    required = set(required_perspectives(cfg, code_changed))
    if not required.issubset(set(normalized)):
        return []

    if not set(normalized).issubset(set(cfg["perspectives"])):
        return []

    return normalized


def write_output(panel: list[str], routing_used: bool, model: str, model_tier: str) -> None:
    """Write router result for composite action output step."""
    payload = {
        "panel": panel,
        "routing_used": bool(routing_used),
        "model": model,
        "model_tier": model_tier,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    print(json.dumps(panel))


def main() -> int:
    """Entrypoint. Never fail workflow; always write output."""
    cerberus_root = os.getenv("CERBERUS_ROOT", ".")
    diff_file = os.getenv("DIFF_FILE", "")
    routing = clean_token(os.getenv("ROUTING", "enabled"))
    forced_reviewers = os.getenv("FORCED_REVIEWERS", "")
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    try:
        cfg = load_config(cerberus_root)
    except Exception as exc:
        warn(f"Failed to load config: {exc}")
        fallback = DEFAULT_PANEL[:5]
        write_output(fallback, False, "fallback", MODEL_TIER_STANDARD)
        return 0

    panel_size = as_int(os.getenv("PANEL_SIZE"), cfg["default_panel_size"])
    panel_size = min(max(panel_size, 1), max(len(cfg["perspectives"]), 1))

    summary = parse_diff(diff_file)
    fallback_panel = build_fallback_panel(cfg, panel_size, summary["code_changed"])

    if forced_reviewers.strip():
        forced_tokens = [part for part in forced_reviewers.split(",")]
        forced_panel = resolve_tokens(forced_tokens, cfg)
        if forced_panel:
            write_output(forced_panel, False, "forced", MODEL_TIER_STANDARD)
            return 0
        warn("Forced reviewers input was set but no valid reviewers were resolved; using fallback panel")
        write_output(fallback_panel, False, "fallback", MODEL_TIER_STANDARD)
        return 0

    if routing == "disabled":
        full_panel = cfg["perspectives"][:]
        if not full_panel:
            full_panel = DEFAULT_PANEL[:]
        write_output(full_panel, False, "disabled", MODEL_TIER_STANDARD)
        return 0

    if not api_key:
        warn("OPENROUTER_API_KEY missing; routing skipped")
        write_output(fallback_panel, False, "fallback", MODEL_TIER_STANDARD)
        return 0

    model_tier = classify_model_tier(summary)
    prompt = build_prompt(cfg, summary, panel_size)
    raw_text, model_used = call_router(api_key, prompt, panel_size)
    parsed_panel = parse_panel_from_text(raw_text)
    validated_panel = validate_panel(parsed_panel, cfg, panel_size, summary["code_changed"])

    if not validated_panel:
        warn("Router returned invalid panel; using fallback panel")
        write_output(
            fallback_panel,
            False,
            model_used or ROUTER_MODEL,
            model_tier,
        )
        return 0

    write_output(
        validated_panel,
        True,
        model_used or ROUTER_MODEL,
        model_tier,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - hard safety net for workflow stability.
        warn(f"Router failed unexpectedly: {exc}")
        try:
            write_output(DEFAULT_PANEL[:5], False, "fallback", MODEL_TIER_STANDARD)
        except Exception:
            print("[]")
        raise SystemExit(0)
