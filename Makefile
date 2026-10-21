.DEFAULT_GOAL := help

.PHONY: help install lint format types test test-bdd test-integration security precommit demo notebooks lite lite-serve test-pyodide test-e2e build clean

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

notebooks: ## Execute every notebook on desktop CPython, without saving outputs
	uv run --frozen jupyter execute --kernel_name=python3 notebooks/*.ipynb

# The site serves lite/contents as its root, laid out the way notebook 5 needs:
# the notebooks beside tests/, pytest.ini and uv.lock. JupyterLite copies the
# children of a contents directory rather than the directory itself, which is
# why the layout is staged here instead of listed in the config. tests/e2e is
# left out: it drives the site from outside and has no place inside it. The
# wheel goes to lite/pypi, which JupyterLite indexes for piplite by convention.
lite: ## Build the browser site into _site/: the banking wheel, the notebooks and the test suite
	rm -rf lite/pypi lite/contents
	uv build --wheel -o lite/pypi
	mkdir -p lite/contents
	cp notebooks/*.ipynb pytest.ini uv.lock lite/contents/
	cp -r tests lite/contents/
	rm -rf lite/contents/tests/e2e
	cd lite && uv run --frozen jupyter lite build --output-dir ../_site

lite-serve: lite ## Build the browser site and serve it on http://localhost:8000
	cd lite && uv run --frozen jupyter lite serve --output-dir ../_site --port 8000

# Twice, because the JavaScript engine decides one result: without JSPI a
# synchronous call cannot run an event loop, so the event_loop tests skip.
# `make` runs recipes in a non-interactive shell, which does not see a node
# that a shell profile puts on PATH lazily (nvm does); pass NODE and NPM then.
NODE ?= node
NPM ?= npm

test-pyodide: lite ## Run every notebook under Pyodide in Node, as the browser kernel would (needs Node.js 24)
	@command -v $(NODE) >/dev/null && command -v $(NPM) >/dev/null || { \
		echo 'test-pyodide needs Node.js 24: put node and npm on PATH, or pass NODE=... NPM=...'; exit 1; }
	cd lite/pyodide && $(NPM) ci --no-audit --no-fund
	$(NODE) lite/pyodide/run_notebooks.mjs
	$(NODE) --experimental-wasm-jspi lite/pyodide/run_notebooks.mjs

test-e2e: lite ## Run every notebook in Chromium and Firefox against the built site (Playwright)
	uv run --frozen playwright install chromium firefox
	uv run --frozen pytest -m e2e --browser chromium --browser firefox

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
	rm -rf _site lite/pypi lite/contents lite/.cache lite/.jupyterlite.doit.db
	find . -path ./.venv -prune -o -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -path ./.venv -prune -o -name '*.py[cod]' -type f -exec rm -f {} +
