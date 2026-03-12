# Issue #361 Walkthrough

## What broke

The verdict action launches [`scripts/lib/github.py`](../../scripts/lib/github.py) as a raw file path. In that mode Python starts with `scripts/lib` on `sys.path`, so `from lib.github_platform import ...` fails before the helper can post the verdict comment.

## Before

```text
$ python3 /tmp/lib/github.py --help
Traceback (most recent call last):
  File "/tmp/lib/github.py", line 14, in <module>
    from lib.github_platform import (
ModuleNotFoundError: No module named 'lib'
```

The branch reproduces that exact failure against the pre-fix `HEAD` version by copying the old file into a temporary `lib/` directory and executing it directly.

## After

```text
$ python3 scripts/lib/github.py --help >/dev/null
$ echo $?
0
```

The helper now prepends `scripts/` only when it is launched as a standalone file, so package imports keep working in both action execution and normal test imports.

## Verification

```text
$ python3 -m pytest tests/test_github.py tests/test_verdict_action.py -q
targeted regression and verdict-action tests passed

$ make validate
pytest, ruff, and shellcheck all passed
```

## Persistent Check

[`tests/test_github.py`](../../tests/test_github.py) now executes `scripts/lib/github.py --help` in a subprocess. That keeps the exact standalone import path alive in CI so this regression cannot slip back in unnoticed.
