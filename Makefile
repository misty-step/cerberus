# Cerberus Makefile
# Quality gates and common tasks

.PHONY: setup test lint shellcheck elixir-test validate help

# Default target
help:
	@echo "Cerberus Quality Gates"
	@echo ""
	@echo "Setup:"
	@echo "  make setup      Install git hooks locally"
	@echo ""
	@echo "Local validation (mirrors CI):"
	@echo "  make test       Run pytest suite"
	@echo "  make lint       Run ruff on all Python files"
	@echo "  make shellcheck Run shellcheck on all scripts"
	@echo "  make elixir-test Run the cerberus-elixir scaffold checks"
	@echo "  make validate   Run test + lint + shellcheck + elixir-test"

# One-command install for git hooks
setup:
	@echo "📦 Installing git hooks..."
	@./scripts/setup-hooks.sh

# Run full pytest suite (used in pre-push, CI)
test:
	python3 -m pytest tests/ -x --timeout=30 -v

# Run ruff linter on all Python files
lint:
	@if command -v ruff >/dev/null 2>&1; then \
		echo "🔍 Running ruff..."; \
		ruff check scripts/ matrix/ tests/; \
	else \
		echo "⚠ ruff not installed. Install with: uv pip install ruff"; \
		exit 1; \
	fi

# Run shellcheck on all shell scripts
shellcheck:
	@if command -v shellcheck >/dev/null 2>&1; then \
		echo "🔍 Running shellcheck..."; \
		find scripts tests api -name "*.sh" -type f -exec shellcheck {} +; \
	else \
		echo "⚠ shellcheck not installed. Install with: brew install shellcheck (macOS) or apt install shellcheck (Linux)"; \
		exit 1; \
	fi

# Run Elixir scaffold verification
elixir-test:
	@if command -v mix >/dev/null 2>&1; then \
		echo "🔍 Running cerberus-elixir checks..."; \
		cd cerberus-elixir && mix deps.get && mix compile && mix test; \
	else \
		echo "⚠ mix not installed. Install Elixir to validate cerberus-elixir"; \
		exit 1; \
	fi

# Full local validation (test + lint + shellcheck + elixir-test)
validate: test lint shellcheck elixir-test
	@echo "✓ All validation checks passed"
