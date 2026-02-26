#!/usr/bin/env python3
"""Read and validate reviewer runtime profile config.

Commands:
  profile-json  Print merged profile JSON for perspective
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.reviewer_profiles import ReviewerProfilesError, load_reviewer_profiles


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="read-reviewer-profile.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    profile_json = sub.add_parser("profile-json")
    profile_json.add_argument("--config", required=True)
    profile_json.add_argument("--perspective", required=True)

    args = parser.parse_args(argv)

    try:
        cfg = load_reviewer_profiles(Path(args.config))
    except ReviewerProfilesError as e:
        print(f"reviewer profiles error: {e}", file=sys.stderr)
        return 2

    if args.cmd == "profile-json":
        perspective = str(args.perspective).strip()
        if not perspective:
            print("reviewer profiles error: --perspective must be non-empty", file=sys.stderr)
            return 2

        profile = cfg.merged_for_perspective(perspective)
        print(
            json.dumps(
                {
                    "provider": profile.provider,
                    "model": profile.model,
                    "thinking_level": profile.thinking_level,
                    "tools": profile.tools,
                    "extensions": profile.extensions,
                    "skills": profile.skills,
                    "max_steps": profile.max_steps,
                    "timeout": profile.timeout,
                },
                sort_keys=True,
            )
        )
        return 0

    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
