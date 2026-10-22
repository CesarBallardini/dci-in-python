# Tooling — dci-in-python

Building, checking and running this repository. The code itself, and what it
demonstrates, are described in [README.md](README.md).

The setup follows the same organization as
[localenv-python](https://github.com/CesarBallardini/localenv-python): linting,
two type checkers, tests separated by kind, and security scanning, configured
from the first commit. It is more tooling than a repository of this size would
normally need. That is deliberate: the repository makes a claim about what a
type checker can and cannot see, so the type checkers have to be configured
strictly enough for the claim to mean something.

# Prerequisites

* [uv](https://docs.astral.sh/uv/) (verified with the latest stable release)
* Python 3.14 (uv installs it automatically if missing, per `.python-version`)
* Git
* [OSV-Scanner](https://google.github.io/osv-scanner/) on `PATH` (only needed for `make security`; on Windows, `choco install osv-scanner`)
* [Node.js](https://nodejs.org/) 24 with `npm` (only needed for `make test-pyodide`)

The package has no runtime dependencies; the DCI mechanism uses only the
standard library. Everything in the `dev` group of `pyproject.toml` exists to
check the code, not to run it, and everything in the `lite` group exists to
build and check the browser site described below.

# Getting started

```bash
git clone https://github.com/CesarBallardini/dci-in-python
cd dci-in-python
make install
```

`make install` syncs the environment from the committed lockfile and installs
the pre-commit hooks. Every task goes through the Makefile from there; the full
list of targets is in [README.md](README.md), and `make` with no target prints
the same list from the Makefile itself.

Use `uv run --frozen` for one-off commands outside the Makefile, so that none of
them rewrites `uv.lock`. The reason is in *Updating dependencies* below.

# What each tool is for

* **[uv](https://docs.astral.sh/uv/)** for dependency and environment management, with separate groups (`dev`, `deploy` and `lite`).
* **[ruff](https://docs.astral.sh/ruff/)** as linter and formatter (`ruff.toml`). Single quotes, line length 119.
* **[pyright](https://microsoft.github.io/pyright/)** + **[pyrefly](https://pyrefly.org/)** as two independent type checkers (`pyrightconfig.json`, `pyrefly.toml`). Both are run because this repository is largely about code a checker can only partly see, and two inference engines over the same code report different things. **Both must report 0 errors and 0 suppressed.** There is no `# type: ignore` or `# pyright: ignore` anywhere in the repository. Where a checker cannot see a runtime fact, the correct response is a commented `typing.cast` that states the fact.
* **[bandit](https://bandit.readthedocs.io/)** (SAST) and **[pip-audit](https://pypi.org/project/pip-audit/)** + **[OSV-Scanner](https://google.github.io/osv-scanner/)** (SCA) against `uv.lock` (`bandit.yaml`). OSV-Scanner is a standalone Go binary rather than a PyPI package, so it is not installed through `uv`: locally it needs to be on `PATH` (`choco install osv-scanner` on Windows), and in CI it runs through Google's official reusable workflow (see `security.yml`).
* **[pytest](https://docs.pytest.org/)** with tests separated by kind: `unit/`, `integration/` (a real SQLite database and [SQLAlchemy](https://www.sqlalchemy.org/)), and `acceptance/` (BDD via [pytest-bdd](https://pytest-bdd.readthedocs.io/), which is where the comparison tables from `README.md` and `APPROACHES.md` are expressed as `Scenario Outline`s). Configured in `pytest.ini`: markers are declared there with `--strict-markers` enabled, so a mistyped marker fails rather than silently selecting nothing, and one warning filter is scoped to a single deprecation in `gherkin-official`. `e2e/` drives the built browser site with Playwright, and is described under *Running in the browser*. Three more markers name a capability a WebAssembly runtime may lack (`threads`, `subprocess`, `event_loop`); `tests/conftest.py` probes for each one and skips the marked tests where it is missing, so on the desktop they change nothing.
* **[pre-commit](https://pre-commit.com/)** hooking lint, format, and lockfile checks before every commit, and [nbstripout](https://github.com/kynan/nbstripout), which removes notebook outputs, so a committed notebook carries no output a fresh run has not produced.
* A `Makefile` as the single entry point for every task.

# Continuous integration

Four independent GitHub Actions workflows in `.github/workflows/`, one per
concern, each with its own badge at the top of the README:

| Workflow | What it runs |
| --- | --- |
| `check.yml` | lint + format + both type checkers |
| `pytest.yml` | the suite, plus the demo as a smoke check |
| `security.yml` | bandit + pip-audit + OSV-Scanner |
| `lite.yml` | builds the browser site, runs every notebook under Pyodide in Node and in Chromium and Firefox, and on `main` publishes the site to GitHub Pages |

Keeping them separate means a failing badge identifies which check failed
without opening the run. The demo runs in CI because its output is quoted in
the blog post: if it stops exiting 0, the post is quoting output that no longer
occurs.

# Running in the browser

The notebooks in `notebooks/` run this repository's `banking` package on
CPython 3.14 compiled to WebAssembly, in a static
[JupyterLite](https://jupyterlite.readthedocs.io/) site that needs no server.
Notebooks 01 to 04 follow the examples of the blog post, the demo and
`APPROACHES.md`, and each one that touches an example the browser cannot run
ends with a section stating which one and why. Notebook 05 runs the test suite
in the browser.

* **[jupyterlite-core](https://pypi.org/project/jupyterlite-core/)** builds the site, and **[jupyterlite-pyodide-kernel](https://pypi.org/project/jupyterlite-pyodide-kernel/)** provides its kernel: [Pyodide](https://pyodide.org/) 314, which is CPython 3.14 for WebAssembly. Their configuration is `lite/jupyter_lite_config.json`.
* **The wheel reaches the browser through the site.** `make lite` builds the `banking` wheel into `lite/pypi/`, which JupyterLite indexes for `piplite`, so a notebook installs this repository's code rather than a copy pasted into cells. The same target stages `lite/contents/`: the notebooks beside `tests/`, `pytest.ini` and `uv.lock`, which is the layout notebook 05 reads. Both directories are generated and ignored.
* **The test dependencies are installed as a fixed set.** Notebook 05 follows `uv.lock` from the suite's direct dependencies to every package that applies on the platform, and installs exactly that closure with `deps=False`. micropip resolves requirements concurrently, so a requirement left to resolution could arrive at a version that depends on the order of the downloads; with the closure pinned there is nothing to resolve. A new direct test dependency has to be added to the roots in that cell.
* **pydantic comes from the Pyodide distribution.** `uv.lock` pins a `pydantic-core` that has no WebAssembly wheel, so notebook 05 installs the pydantic that Pyodide ships, with its own dependencies, in a second call made after the pinned set, and prints what arrived. Notebook 04 prints the library versions it ran with.
* **Some tests skip in the browser.** Pyodide cannot start a thread or a process, and it runs an event loop from synchronous code only where the JavaScript engine supports JSPI. The tests that need one of those carry the `threads`, `subprocess` or `event_loop` marker and are skipped with that reason; nothing is edited to pass. Chromium and Firefox both support JSPI, so in either browser notebook 05 skips only the `threads` and `subprocess` tests.

Four targets cover it:

| Target | What it checks |
| --- | --- |
| `make notebooks` | every notebook runs on desktop CPython |
| `make lite-serve` | builds the site and serves it on `http://localhost:8000`, for reading it in a browser |
| `make test-pyodide` | every notebook runs under the Pyodide release the kernel bundles, in Node (`lite/pyodide/run_notebooks.mjs`), once without JSPI and once with it |
| `make test-e2e` | every notebook of the built site runs in Chromium and Firefox, driven by [Playwright](https://playwright.dev/python/) (`tests/e2e/`) |

`make test-pyodide` needs `node` and `npm` on the `PATH` of a non-interactive
shell. A version manager that adds them lazily from a shell profile does not,
and then the paths can be passed: `make test-pyodide NODE=/path/to/node
NPM=/path/to/npm`. The `e2e` tests are deselected from `make test`, because
they need the built site and installed browsers; `make test-e2e` provides both.

`lite.yml` publishes the site to GitHub Pages on every push to `main`. That
requires Pages to be enabled with *GitHub Actions* as its source, which is a
repository setting the workflow cannot change.

# Updating dependencies

By default, `uv run` and `uv sync` may re-resolve and rewrite `uv.lock` if they
detect that `pyproject.toml` has changed. That is acceptable during development,
but any command whose purpose is only to *run* something — CI, a first install,
an ordinary `make test` — should pin the lockfile to what is committed:

```bash
uv sync --frozen              # installs exactly what uv.lock says, resolves nothing
uv run --frozen pytest        # same idea, for any one-off command
```

The pre-commit hook (`uv lock --check`) fails if `uv.lock` and `pyproject.toml`
are out of sync.

Updating dependencies is done explicitly:

```bash
uv lock --upgrade-package ruff   # updates just that package to the max pyproject.toml allows
uv lock --upgrade                # updates everything pyproject.toml's constraints allow
```

Both commands rewrite `uv.lock`. Review the diff (`git diff uv.lock`) before
continuing, and run the full suite before committing:

```bash
uv sync --all-groups
make lint types test security
```

# Building a wheel

The installable package is `banking`. The `[project] name` and the importable
package name match deliberately; see `[tool.hatch.build.targets.wheel]` in
`pyproject.toml`, with `hatchling` as the build backend. To build the wheel:

```bash
make build
```

`make build` runs `lint`, `types` and `test` first and stops if any of them
fails, so nothing that has not passed the checks reaches `dist/`. It then runs
`uv build`, which writes both a source distribution and a wheel there.

`dist/` is gitignored and `uv build` does not empty it, so a previous version's
artifacts stay unless they are removed. `make clean` removes them, along with
the tool caches, `__pycache__` directories and any coverage output. It leaves
`.venv/` alone: that is also gitignored, but rebuilding it means another
`make install`.

The `py.typed` marker in `src/banking/` is included in the wheel, so a project
that installs this package receives its type hints rather than having a type
checker treat it as `Any`.
