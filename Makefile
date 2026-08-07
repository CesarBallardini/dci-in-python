.DEFAULT_GOAL := help

.PHONY: help install lint format types test test-bdd test-integration security precommit demo build clean

help: ## Show this list of available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Sync the environment (from the committed lockfile) and install pre-commit hooks
	uv sync --all-groups --frozen
	uv run --frozen pre-commit install

lint: ## Check formatting and lint rules without modifying files
	uv run --frozen ruff check .
	uv run --frozen ruff format --check .

format: ## Auto-fix formatting and lint issues
	uv run --frozen ruff format .
	uv run --frozen ruff check --fix .

types: ## Run both type checkers (pyright + pyrefly)
	uv run --frozen pyright
	uv run --frozen pyrefly check

test: ## Run the whole suite (unit + integration + acceptance)
	uv run --frozen pytest

test-bdd: ## Run only the BDD/acceptance tests (pytest-bdd)
	uv run --frozen pytest -m bdd

test-integration: ## Run only the integration tests (real SQLite DB + SQLAlchemy)
	uv run --frozen pytest -m integration

demo: ## Run every example in the documentation, including the five-styles sweep
	uv run --frozen python demo/dci_demo.py

security: ## Run security scans (bandit SAST + pip-audit + OSV-Scanner SCA)
	uv run --frozen bandit -c bandit.yaml -r src
	uv run --frozen pip-audit --skip-editable
	osv-scanner --lockfile=./uv.lock

precommit: ## Run all pre-commit hooks against every file
	uv run --frozen pre-commit run --all-files

build: lint types test ## Check everything, then build the sdist and the wheel into dist/
	uv build

# Everything removed here is listed in .gitignore, so nothing tracked can be
# lost. `.venv/` is the one exception: it is ignored too, but rebuilding it
# means another `make install`, which is not what "clean" should cost.
clean: ## Remove build artifacts, caches and coverage output (keeps .venv)
	rm -rf dist build htmlcov .pytest_cache .ruff_cache .mypy_cache .pyrefly_cache
	rm -rf ./*.egg-info src/*.egg-info
	rm -f .coverage coverage.xml
	find . -path ./.venv -prune -o -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -path ./.venv -prune -o -name '*.py[cod]' -type f -exec rm -f {} +
