# Cerberus Makefile
# Quality gates and common tasks

.PHONY: setup test lint shellcheck yamllint elixir-test validate help

# Require a CLI tool or fail with install instructions.
# Usage: $(call require,<cmd>,<install hint>)
define require
@command -v $(1) >/dev/null 2>&1 || { echo "⚠ $(1) not installed. Install with: $(2)"; exit 1; }
endef

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
	@echo "  make yamllint   Run yamllint on workflow YAML"
	@echo "  make elixir-test Run the cerberus-elixir scaffold checks"
	@echo "  make validate   Run test + lint + shellcheck + yamllint + elixir-test"

# One-command install for git hooks
setup:
	@echo "📦 Installing git hooks..."
	@./scripts/setup-hooks.sh

# Run full pytest suite (used in pre-push, CI)
test:
	python3 -m pytest tests/ -x --timeout=30 -v

# Run ruff linter on all Python files
lint:
	$(call require,ruff,uv pip install ruff)
	@echo "🔍 Running ruff..."
	@ruff check scripts/ matrix/ tests/

# Run shellcheck on all shell scripts
shellcheck:
	$(call require,shellcheck,brew install shellcheck (macOS) or apt install shellcheck (Linux))
	@echo "🔍 Running shellcheck..."
	@find scripts tests api cerberus-elixir \
		-path 'cerberus-elixir/_build' -prune -o \
		-path 'cerberus-elixir/deps' -prune -o \
		-name "*.sh" -type f -exec shellcheck {} +

# Run yamllint on workflow YAML
yamllint:
	$(call require,yamllint,pip install yamllint)
	@echo "🔍 Running yamllint..."
	@yamllint .github/workflows/*.yml

# Run Elixir scaffold verification
elixir-test:
	$(call require,mix,Install Elixir to validate cerberus-elixir)
	@echo "🔍 Running cerberus-elixir checks..."
	@cd cerberus-elixir && mix deps.get && mix compile && mix test && ./test/release_contract.sh

# Full local validation (test + lint + shellcheck + yamllint + elixir-test)
validate: test lint shellcheck yamllint elixir-test
	@echo "✓ All validation checks passed"
