#!/bin/bash
#
# Setup script for Cerberus git hooks
# One-command install for local development
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.githooks"
GIT_DIR="$REPO_ROOT/.git"

echo "📦 Setting up Cerberus git hooks..."

# Check if we're in a git repo
if [ ! -d "$GIT_DIR" ]; then
    echo "✗ Error: Not a git repository"
    exit 1
fi

# Check if hooks directory exists
if [ ! -d "$HOOKS_DIR" ]; then
    echo "✗ Error: .githooks directory not found at $HOOKS_DIR"
    exit 1
fi

# Install hooks
echo "  → Installing hooks to $GIT_DIR/hooks..."

for hook in pre-commit pre-push; do
    if [ -f "$HOOKS_DIR/$hook" ]; then
        cp "$HOOKS_DIR/$hook" "$GIT_DIR/hooks/$hook"
        chmod +x "$GIT_DIR/hooks/$hook"
        echo "    ✓ Installed: $hook"
    else
        echo "    ⚠ Hook not found: $HOOKS_DIR/$hook"
    fi
done

# Configure git to use local hooks (in case core.hooksPath is set elsewhere)
git config --local core.hooksPath "$GIT_DIR/hooks"

echo ""
echo "✅ Git hooks installed successfully!"
echo ""
echo "Hook summary:"
echo "  • pre-commit: Fast checks (<5s) on staged files only"
echo "      - shellcheck on *.sh files"
echo "      - py_compile on scripts/*.py and scripts/lib/*.py"
echo "      - ruff lint on Python files"
echo "      - YAML validation (Python) on *.yml files"
echo "      - JSON validation (Python) on *.json files"
echo ""
echo "  • pre-push: Thorough checks (<60s) on all files"
echo "      - Full pytest suite (tests/ -x --timeout=30)"
echo "      - shellcheck on ALL shell scripts"
echo "      - ruff check on all Python files"
echo ""
echo "To bypass hooks in emergencies:"
echo "  git commit --no-verify    # Skip pre-commit"
echo "  git push --no-verify     # Skip pre-push"
