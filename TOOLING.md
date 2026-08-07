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

The package has no runtime dependencies; the DCI mechanism uses only the
standard library. Everything in the `dev` group of `pyproject.toml` exists to
check the code, not to run it.

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

* **[uv](https://docs.astral.sh/uv/)** for dependency and environment management, with separate groups (`dev` vs `deploy`).
* **[ruff](https://docs.astral.sh/ruff/)** as linter and formatter (`ruff.toml`). Single quotes, line length 119.
* **[pyright](https://microsoft.github.io/pyright/)** + **[pyrefly](https://pyrefly.org/)** as two independent type checkers (`pyrightconfig.json`, `pyrefly.toml`). Both are run because this repository is largely about code a checker can only partly see, and two inference engines over the same code report different things. **Both must report 0 errors and 0 suppressed.** There is no `# type: ignore` or `# pyright: ignore` anywhere in the repository. Where a checker cannot see a runtime fact, the correct response is a commented `typing.cast` that states the fact.
* **[bandit](https://bandit.readthedocs.io/)** (SAST) and **[pip-audit](https://pypi.org/project/pip-audit/)** + **[OSV-Scanner](https://google.github.io/osv-scanner/)** (SCA) against `uv.lock` (`bandit.yaml`). OSV-Scanner is a standalone Go binary rather than a PyPI package, so it is not installed through `uv`: locally it needs to be on `PATH` (`choco install osv-scanner` on Windows), and in CI it runs through Google's official reusable workflow (see `security.yml`).
* **[pytest](https://docs.pytest.org/)** with tests separated by kind: `unit/`, `integration/` (a real SQLite database and [SQLAlchemy](https://www.sqlalchemy.org/)), and `acceptance/` (BDD via [pytest-bdd](https://pytest-bdd.readthedocs.io/), which is where the comparison tables from `README.md` and `APPROACHES.md` are expressed as `Scenario Outline`s). Configured in `pytest.ini`: markers are declared there with `--strict-markers` enabled, so a mistyped marker fails rather than silently selecting nothing, and one warning filter is scoped to a single deprecation in `gherkin-official`. There is no `e2e/` directory: this is a library, with no running instance to drive.
* **[pre-commit](https://pre-commit.com/)** hooking lint, format, and lockfile checks before every commit.
* A `Makefile` as the single entry point for every task.

# Continuous integration

Three independent GitHub Actions workflows in `.github/workflows/`, one per
concern, each with its own badge at the top of the README:

| Workflow | What it runs |
| --- | --- |
| `check.yml` | lint + format + both type checkers |
| `pytest.yml` | the suite, plus the demo as a smoke check |
| `security.yml` | bandit + pip-audit + OSV-Scanner |

Keeping them separate means a failing badge identifies which check failed
without opening the run. The demo runs in CI because its output is quoted in
the blog post: if it stops exiting 0, the post is quoting output that no longer
occurs.

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
