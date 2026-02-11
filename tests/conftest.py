"""Import helpers for scripts that aren't packages."""
import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"

# Add scripts/ to sys.path so aggregate-verdict.py can import lib.overrides.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _import_script(name: str, filename: str):
    """Import a script file as a module using importlib."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


parse_review = _import_script("parse_review", "parse-review.py")
aggregate_verdict = _import_script("aggregate_verdict", "aggregate-verdict.py")
