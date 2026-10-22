# README - dci-in-python

[![check](https://github.com/CesarBallardini/dci-in-python/actions/workflows/check.yml/badge.svg)](https://github.com/CesarBallardini/dci-in-python/actions/workflows/check.yml)
[![pytest](https://github.com/CesarBallardini/dci-in-python/actions/workflows/pytest.yml/badge.svg)](https://github.com/CesarBallardini/dci-in-python/actions/workflows/pytest.yml)
[![security](https://github.com/CesarBallardini/dci-in-python/actions/workflows/security.yml/badge.svg)](https://github.com/CesarBallardini/dci-in-python/actions/workflows/security.yml)
[![lite](https://github.com/CesarBallardini/dci-in-python/actions/workflows/lite.yml/badge.svg)](https://github.com/CesarBallardini/dci-in-python/actions/workflows/lite.yml)

DCI — *Data, Context, Interaction* — implemented in Python from scratch with no dependencies: roles attached to live objects for the duration of a context, in about thirty lines of standard library.

This is the companion repository for two posts, both written in Spanish:

* [DCI: la idea olvidada del hombre que inventó MVC](https://katra.ballardini.com.ar/posts/dci-data-context-interaction-reenskaug/) — *"DCI: the forgotten idea of the man who invented MVC"*. Where DCI came from and what it proposes.
* [DCI en Python: roles en runtime](https://katra.ballardini.com.ar/posts/dci-en-python-roles-en-runtime/) — *"DCI in Python: roles at runtime"*. This code.

```bash
git clone https://github.com/CesarBallardini/dci-in-python
cd dci-in-python
make install
make demo
make test
```

The same code also runs in the browser, on CPython 3.14 compiled to WebAssembly, with nothing installed: [the notebooks](https://katra.ballardini.com.ar/dci-in-python/) run the examples of the blog post and the test suite. The first load downloads the Python runtime and takes a while.

Every task goes through the Makefile. `make` with no target prints this list:

| Target | What it does |
| --- | --- |
| `make install` | Sync the environment from the committed lockfile, and install the pre-commit hooks |
| `make demo` | Run every example in the documentation, including the five-styles sweep |
| `make lint` | `ruff check` + `ruff format --check`, without modifying files |
| `make format` | `ruff format` + `ruff check --fix`, applying the fixes |
| `make types` | Both type checkers: pyright, then pyrefly |
| `make test` | The whole suite: unit, integration and acceptance |
| `make test-bdd` | Only the acceptance tests (`pytest -m bdd`) |
| `make test-integration` | Only the integration tests: real SQLite database and SQLAlchemy |
| `make security` | bandit (SAST), pip-audit and OSV-Scanner (SCA) |
| `make precommit` | Run every pre-commit hook against every file |
| `make notebooks` | Run every notebook on desktop CPython, without saving outputs |
| `make lite` | Build the browser site into `_site/`: the `banking` wheel, the notebooks and the test suite |
| `make lite-serve` | Build the browser site and serve it on `http://localhost:8000` |
| `make test-pyodide` | Run every notebook under Pyodide in Node, as the browser kernel would (needs Node.js 24) |
| `make test-e2e` | Run every notebook of the built site in Chromium and Firefox (Playwright) |
| `make build` | `lint types test`, then build the sdist and the wheel into `dist/` |
| `make clean` | Remove build artifacts, caches and coverage output; keeps `.venv` |
| `make help` | The same list, from the Makefile |

Two companion documents keep this one focused on the findings:

* **[TOOLING.md](TOOLING.md)** — prerequisites, what each tool is for, CI, running in the browser, updating dependencies, building a wheel.
* **[APPROACHES.md](APPROACHES.md)** — the same transfer implemented every way it can be: the four role binders and the five designs, with both comparison tables.

# The transfer, and the mechanism

The canonical DCI example is a bank transfer. `Account` has no knowledge of transfers; it knows how to debit and credit itself. `SourceAccount` and `DestinationAccount` are *roles*: behaviour attached to an object while a context runs. `MoneyTransferContext` is the use case as an object, and its script is a single line.

```python
class MoneyTransferContext(Context):
    roles = {
        'source': SourceAccount,
        'destination': DestinationAccount,
        'amount': TransferAmount,
    }

    def execute(self) -> None:
        with self:
            self.source.transfer()
```

The amount is the third role, which is why the script passes nothing: `transfer()` takes no arguments. Why a sum of money is a participant rather than a parameter is in `banking/roles/money_transfer.py`.

Inside the context, the source account plays the `SourceAccount` role, and it plays it by **being** one: within the `with` block, `isinstance(account, SourceAccount)` and `isinstance(account, Account)` are both true. The account was not wrapped and it was not copied — it has the same `id()` as before, and it now has a `transfer()` method that `Account` does not define. Leaving the context takes the role away again.

This works because Python allows the class of a live object to be reassigned. Entering builds a class that combines the role with the object's own class, and installs it:

```python
obj.__class__ = _class_with_role(obj.__class__, role)  # Account  ->  Account@SourceAccount
```

That line is the mechanism. The rest of `banking/dci/` is the lifecycle around it: binding every participant when the context opens, releasing them when it ends, and letting a role reach its peers.

# Structure

The package is `banking`. DCI is the mechanism the domain is written with, so the machinery is a package inside the domain package, and the layout follows the three letters: `data/` is Data, `contexts/` is Context, and `roles/` is Interaction — the roles and the script between them.

Everything the repository varies is one module per item, with its own tests: the four binders under `dci/`, and the three designs DCI argues against under `alternatives/`. `services/` holds the fifth design, the one that keeps DCI's structure and drops the mechanism.

```
src/banking/
  dci/                        # the mechanism, one binder per module
    __init__.py               # the public names, and the four binders compared
    base.py                   # context(), BaseContext: the lifecycle and the two guards
    class_binding.py          # Context: the role mixed into the object's class
    transparent.py            # TransparentContext: the synthesized class renamed
    serialized.py             # SerializedContext: the participants locked
    instance.py               # InstanceContext: the role written into the instance
  data/                       # Data
    account.py                # what an account is: holder, balance, debit, credit
    money.py                  # value object: an amount and a currency label
  roles/                      # Interaction
    money_transfer.py         # SourceAccount, DestinationAccount, TransferAmount
  contexts/                   # Context
    money_transfer.py         # the use case, reified once per binder
  services/
    money_transfer.py         # the same use case as a service, without the mechanism
  alternatives/               # the designs DCI argues against, one per module
    fat_account.py            # design 1: the transfer placed on the entity
    anemic_service.py         # design 2: the record, and the procedure over it
    role_as_wrapper.py        # the role as a wrapper: no binding, and no identity
demo/
  dci_demo.py                 # the transfer, the four breakages, and the five styles
notebooks/                    # the same material, run in the browser
  01-the-mechanism.ipynb      # the two conventional versions, then roles bound, temporary, identity kept
  02-four-binders.ipynb       # the four binders, pickle, and a role that contributes a dunder
  03-where-python-says-no.ipynb  # the breakages, and the overlap reproduced with asyncio tasks
  04-five-designs.ipynb       # which domain objects can play a role, the wrapper, and the service
  05-run-the-tests.ipynb      # the test suite, run by pytest in the notebook
lite/
  jupyter_lite_config.json    # the JupyterLite site build
  pyodide/                    # run_notebooks.mjs: every notebook under Pyodide in Node
tests/
  conftest.py                 # the alice and bob fixtures, and the capability skips
  unit/                       # no infrastructure, fast
    test_money_transfer.py    # the money moves
    test_roles.py             # roles are temporary, contextual, identity-preserving
    test_money.py             # the value object
    test_limits.py            # where class binding fails, asserted rather than described
    test_transparent_roles.py # the renamed class: what it fixes and what it only hides
    test_serialized_roles.py  # the locks: four measured properties
    test_instance_roles.py    # instance binding: what it gains and what it costs
    test_money_transfer_service.py  # the service, and the limits it does not have
    test_async_overlap.py     # the overlapping contexts, served by two asyncio tasks
    test_fat_account.py       # the money moves, and the entity has absorbed the use case
    test_anemic_service.py    # the money moves, and no role exists as an object
    test_role_as_wrapper.py   # the wrapper: what it survives, and what it costs
  integration/
    test_orm_roles.py         # a real database: can a persisted entity play a role?
  acceptance/                 # Gherkin: the use case, and APPROACHES.md's tables
    features/
      money_transfer.feature  # the transfer as a user would describe it
      role_binding.feature    # which domain objects can play a role, row by row
      role_binders.feature    # the four binders compared, cell by cell
    steps/                    # one pytest-bdd step module per feature
  e2e/
    test_notebooks_in_browser.py  # every notebook of the built site, run in two browsers
```

# Every way of writing it

The same transfer is implemented repeatedly along two axes, and both comparisons are in **[APPROACHES.md](APPROACHES.md)**:

* **Four ways to bind a role** — `banking/dci/` provides `Context`, `TransparentContext`, `SerializedContext` and `InstanceContext`, which differ in how a role is attached. These vary the *mechanism*. Each is described there with the failures it has, the failure it answers, and what the answer costs.
* **Five ways to write the transfer** — DCI against the fat account, the anemic account with a service, the role-as-wrapper, and a service that gives up only identity. These vary the *design*.

Which domain objects can play a role at all — plain classes, pydantic models, frozen dataclasses, slotted classes, and ORM entities mapped both ways — is measured there as well.

# License

MIT — see [LICENSE](LICENSE).
