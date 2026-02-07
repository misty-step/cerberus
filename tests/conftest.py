"""Import helpers for scripts that aren't packages."""
import importlib.util
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _import_script(name: str, filename: str):
    """Import a script file as a module using importlib."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


parse_review = _import_script("parse_review", "parse-review.py")
aggregate_verdict = _import_script("aggregate_verdict", "aggregate-verdict.py")
