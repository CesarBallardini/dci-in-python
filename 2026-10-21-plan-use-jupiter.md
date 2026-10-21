# Plan — running the repository in the browser (JupyterLite, Pyodide, WebAssembly)

Written 2026-10-21, from the code. Sources read: `pyproject.toml`, `Makefile`,
`pytest.ini`, `.github/workflows/pytest.yml`, `demo/dci_demo.py`, and a scan of
`src/` and `tests/` for the features that behave differently under
WebAssembly (threads, SQLite, files, compiled dependencies). The asyncio
results quoted below come from two scratch scripts run on desktop CPython
3.14.8 against this repository's four binders, on 2026-10-21.

## Status

Implemented on 2026-10-21 with the proposed answer to each open decision:
GitHub Pages hosting, the suite in the browser behind capability markers, no
blog link, and the `SerializedContext` limit documented rather than answered
with a fifth binder. Two items remain open: enabling Pages, which is a
repository setting, and the Binder link, which was dropped.

Where the implementation differs from the phases below:

- **Three capability markers, not one.** `threads`, `subprocess` (the pickle
  test that loads bytes in a second interpreter) and `event_loop` (the asyncio
  tests, which call `asyncio.run` from synchronous code). `tests/conftest.py`
  probes for each capability instead of checking `sys.platform`, so a desktop
  notebook, whose kernel is already running a loop, skips `event_loop` too.
- **The event loop depends on the JavaScript engine.** `asyncio.run` under
  Pyodide needs JSPI. Chromium 156 and Firefox 157 have it, so notebook 05 runs
  141 tests and skips 19 there; Node without `--experimental-wasm-jspi` runs 132
  and skips 28. On the desktop, `make test` runs 160 and a desktop notebook 151.
- **The Node check uses the `pyodide` npm package, not `pyodide venv`.**
  `lite/pyodide/run_notebooks.mjs` pins the Pyodide release the kernel bundles,
  serves the wheel from the build, and runs every notebook's cells in order.
  `make test-pyodide` runs it with and without JSPI.
- **Playwright end-to-end tests.** `tests/e2e/` opens every notebook of the
  built site in Chromium and Firefox and runs all cells (`make test-e2e`). They
  carry the `e2e` marker and are deselected from `make test`.
- **The contents are staged.** JupyterLite copies the children of a contents
  directory, not the directory, so `make lite` lays out `lite/contents/` with the
  notebooks beside `tests/`, `pytest.ini` and `uv.lock`, and the wheel goes to
  `lite/pypi/`. The output directory is passed as `--output-dir`, because the
  config file does not accept it.
- **pydantic comes from the Pyodide distribution** (2.12.5 with pydantic-core
  2.41.5), because `uv.lock` pins a pydantic-core with no WebAssembly wheel. The
  other pure-Python test dependencies are pinned to `uv.lock` by notebook 05.

---

## Goal

A reader opens a URL and gets a Jupyter notebook running **this repository's
`banking` package** on CPython 3.14 compiled to WebAssembly, with nothing
installed locally. The notebooks walk through the same material as the demo
and `APPROACHES.md`, and one notebook runs the test suite in the browser.

The repository exists to measure how far Python 3.14 carries DCI. A second
runtime fits that purpose only if it is treated the same way: what works in
the browser is shown running, and what does not is shown failing, with the
reason. The notebooks are therefore a second measurement, not a port.

## The stack

| Layer | Choice | Why |
| --- | --- | --- |
| Interpreter | Pyodide **314.x** (CPython 3.14.2, Emscripten 5.0.3, released 2026-06-09) | `requires-python = ">=3.14"`; micropip honours `Requires-Python`, so an older Pyodide (0.28 = 3.13) cannot install the wheel at all. It would also change the subject: the repository measures 3.14 |
| Notebook front end | JupyterLite (`jupyterlite-core`) | A static site: Jupyter in the browser with no server, deployable to GitHub Pages |
| Kernel | `jupyterlite-pyodide-kernel` **0.8.x** | The release line that bundles Pyodide 314 / Python 3.14. 0.7.x ships an older Pyodide |
| Package delivery | The `banking` wheel (`uv build --wheel`, pure Python, `py3-none-any`) placed in the site's `pypi/` folder | `jupyter lite build` indexes it for piplite, so a notebook runs `%pip install banking` and gets this repository's code, not a copy pasted into cells |

Rejected: **xeus-python for JupyterLite** (emscripten-forge packages; the
Python version and the availability of SQLAlchemy and pydantic would have to be
checked separately, and it adds a conda environment to the tooling) and
**PyScript** (a page, not a notebook, which is not what was asked).

## What changes under WebAssembly

Each row is a hypothesis until Phase 0 confirms it.

| Feature | Used by | Expected in Pyodide 314 | Consequence |
| --- | --- | --- | --- |
| `obj.__class__ = ...`, `__slots__` layout rule, `ContextVar`, `weakref.finalize` | the whole mechanism, `test_limits.py` | Identical: it is the same CPython | Sections 1 to 5b and 6 of the demo, and the four binders, behave as on the desktop. This is the point to verify first |
| `threading.Thread.start()` | demo 6b; `test_limits.py` (2 tests), `test_serialized_roles.py` (about 5), `test_instance_roles.py` (1), `test_money_transfer_service.py` (1), `steps/test_role_binders_steps.py` (2 step functions) | Raises `RuntimeError` (no pthreads in the default build) | The threaded tests cannot run in the browser. `threading.Lock`/`RLock`/`Event` objects still construct; a lock never waits, because there is only one thread. The overlap itself is reproduced with asyncio instead (next section) |
| `asyncio` | nothing yet; added by this plan | Works: Pyodide runs asyncio on the browser's event loop. Top-level `await` works in a notebook cell; `asyncio.run()` does not, because a loop is already running | Demo 6b and the different-roles leak are reproduced with two tasks, no threads |
| `sqlite3` | `test_orm_roles.py`, `steps/test_role_binding_steps.py`, demo section 8 | Back in the 314 standard library | Works; `tmp_path` files live in the in-memory filesystem |
| SQLAlchemy, attrs | demo 8, integration, acceptance | SQLAlchemy is in the Pyodide distribution; attrs is pure Python | Should work. Versions may differ from `uv.lock` |
| pydantic | demo 8, integration | Needs `pydantic_core`, a compiled package; available from the Pyodide distribution or, under PEP 783, a `pyemscripten_2026_0` wheel on PyPI | Must be confirmed. A different pydantic version can change a five-designs outcome, which is a finding, not a bug |
| pytest, pytest-bdd, gherkin-official, factory-boy, faker | test suite | pytest is in the distribution; the rest are pure Python | Should work |
| pytest-xdist, pytest-cov | CI only | xdist needs processes | Not installed in the browser |

## Threads in the browser, and the asyncio replacement

**Why there are no threads.** WebAssembly gets threads only through the
browser: one Web Worker per thread, a `SharedArrayBuffer` as the shared heap,
and `Atomics` for waiting. Pyodide does not build CPython that way, for three
reasons. Pthreads combined with Emscripten's dynamic linking, which Pyodide
uses to load every compiled package, is described by Pyodide itself as slow
and unreliable, and a threaded build would be a separate ABI that every package
has to be rebuilt for. `SharedArrayBuffer` is only enabled on pages served with
cross-origin isolation headers (COOP/COEP), which GitHub Pages cannot set and
which block resources from CDNs that do not opt in. The browser's main thread
cannot block on `Atomics.wait`. The standard Pyodide build therefore has no
pthreads, and starting a thread raises `RuntimeError`.

**What replaces them.** The finding the threaded tests demonstrate is not
about threads: it is one object in memory inside two live contexts at once.
`asyncio` produces exactly that on a single thread, when two tasks are
suspended at an `await` inside their contexts. Run on desktop CPython with the
repository's binders, unchanged:

| Scenario (two tasks, no threads) | `Context` / `TransparentContext` | `SerializedContext` | `InstanceContext` |
| --- | --- | --- | --- |
| Same role (demo 6b) | second task: `TypeError` (MRO) | second task: `TypeError` (MRO) | second task: `RuntimeError` (refuses) |
| Different roles, overlapping without nesting | `AttributeError: ... no attribute 'receive'`; after both leave, `shared` still has `.transfer` | same as `Context` | no failure; nothing left behind |

Every outcome matches the threaded results **except `SerializedContext`**.
Its lock is an `RLock` owned by a thread, and all tasks run on the same
thread, so the second task acquires it at once and nothing is serialized. This
is consistent with the class docstring ("Nor does it apply within one thread"),
but no test asserts it for asyncio, and the post's decision table recommends
`SerializedContext` for shared objects without qualification. In an
asynchronous application that recommendation does not hold. See open
decision 4.

**Alternatives considered for real threads, and rejected:**

| Option | Reproduces the overlap | Why not |
| --- | --- | --- |
| A CPython built for Emscripten with `--enable-wasm-pthreads`, served with COOP/COEP | Yes | A custom interpreter build to maintain; not supported by JupyterLite or micropip; not the runtime a reader has |
| One Pyodide per Web Worker | No | Separate heaps mean separate objects, the same reason processes never collide |
| A remote kernel (Binder, Codespaces) with the JupyterLab UI in the browser | Yes, real threads | Not WebAssembly. Kept as an optional extra in Phase 4 |

## Constraints from `CLAUDE.md`

- `demo/dci_demo.py` is **not modified**. Its output is quoted in the blog
  post, and it cannot run end to end in the browser because of 6b. The
  notebooks import `banking` and re-state the examples; they do not execute the
  demo file.
- `tests/unit/test_limits.py` is not repaired. Thread-dependent tests are
  skipped in the browser by an explicit marker, never edited to pass.
- No claim in the notebooks without a cell that demonstrates it. Version-
  dependent outcomes (pydantic, SQLAlchemy) print the library version beside
  the result.
- English only, the repository register, ruff single quotes and line length 119.
- Each tool keeps its own config file: JupyterLite's goes in
  `lite/jupyter_lite_config.json`, not in `pyproject.toml`.
- Zero type suppressions still holds. Notebooks contain no annotations that
  would need one.

## Layout

```
lite/
  jupyter_lite_config.json   # output dir, piplite URLs, kernel settings
  pypi/                      # banking-*.whl copied here by `make lite` (gitignored)
notebooks/
  01-the-mechanism.ipynb      # demo 1-4: roles bound, temporary, identity kept
  02-four-binders.ipynb       # Context, Transparent, Serialized, Instance; the comparison table
  03-where-python-says-no.ipynb  # __slots__, frozen dataclass, overlapping contexts, pickle;
                              # the overlap reproduced with two asyncio tasks, all four binders
  04-five-designs.ipynb       # demo 8 and the persistence finding, with library versions
  05-run-the-tests.ipynb      # pytest in the browser, threads skipped, summary printed
```

The tests are not in the wheel. `05-run-the-tests.ipynb` needs `tests/` in the
browser filesystem: `jupyter lite build --contents tests` copies it into the
site's file browser, and the notebook runs `pytest.main(['tests', '-p',
'no:cacheprovider', '-m', 'not threads'])`.

## Phases

### Phase 0 — confirm the runtime (spike, nothing committed)

- [x] Pin the versions: latest `jupyterlite-core` and `jupyterlite-pyodide-kernel`
      0.8.x; confirm from its release notes that it bundles Pyodide 314.x.
- [x] In a scratch JupyterLite site, `%pip install` the built wheel and run demo
      sections 1 to 6 by hand. Confirm `type(a).__name__` and every error message
      matches the desktop output character for character.
- [x] Confirm `threading.Thread(...).start()` raises, and record the exact message.
- [x] Run the two asyncio scenarios in a notebook cell with top-level `await`, for all
      four binders. Expected: the table in "Threads in the browser" above, unchanged.
- [x] Check whether a synchronous test can drive an event loop under Pyodide's pytest
      (`asyncio.run`, or `run_until_complete`, which needs JSPI in the browser). This
      decides whether the asyncio tests of Phase 2 run in notebook 05 or only on the
      desktop.
- [x] Install pydantic, SQLAlchemy, attrs; run demo section 8; record versions and
      the five outcomes.
- [x] Install pytest, pytest-bdd, factory-boy, faker; run the whole suite; produce the
      exact list of failing tests. The expectation is that every failure is a thread
      failure. Any other failure is a finding and goes to the user before Phase 2.
- [x] Repeat the suite outside the browser with `pyodide venv` (from `pyodide-build`)
      under Node. If it gives the same result, it becomes the CI check in Phase 4.

Exit criterion: a table of desktop vs browser results for every demo section and
every test. If the mechanism itself differs anywhere, stop and re-plan.

### Phase 1 — tooling

- [x] New dependency group `lite` in `pyproject.toml`: `jupyterlite-core`,
      `jupyterlite-pyodide-kernel`. Then `uv lock` (the one command here that is
      expected to rewrite `uv.lock`).
- [x] `lite/jupyter_lite_config.json`: output to `_site/`, `piplite_urls` pointing
      at `lite/pypi/`, contents `notebooks/` and `tests/`.
- [x] Makefile targets:
      `lite` — `uv build --wheel`, copy the wheel to `lite/pypi/`, `jupyter lite build`;
      `lite-serve` — `jupyter lite serve` on the built site for local checking.
      Both added to `.PHONY` and given `##` help text.
- [x] `.gitignore`: `_site/`, `lite/pypi/*.whl`, `.jupyterlite.doit.db`.
- [x] `make clean` removes `_site/` and the copied wheel.

### Phase 2 — the asyncio tests and the browser marker

- [x] New `tests/unit/test_async_overlap.py`, standard library only (`asyncio.run`
      inside synchronous tests, no `pytest-asyncio`), asserting the asyncio table above:
      - same role: `TypeError` (MRO) for the three class binders, `RuntimeError` for
        `InstanceContext`;
      - different roles, non-nested: the leak for `Context`, `TransparentContext` and
        `SerializedContext`, no leak for `InstanceContext`;
      - `test_serialized_does_not_serialize_asyncio_tasks`: a deliberate failure, in
        the manner of `test_limits.py`, stating that the lock belongs to the thread
        and every task shares it.
- [x] If Phase 0 found that pytest under Pyodide cannot drive an event loop, give
      these tests a marker of their own and skip them in the browser; notebook 03
      runs the same scenarios with top-level `await` there instead.
- [x] Register a `threads` marker in `pytest.ini`: "starts OS threads; cannot run
      where the runtime has none".
- [x] Mark the thread-starting tests found in Phase 0 with `@pytest.mark.threads`, and
      tag the matching Gherkin scenarios `@threads` (pytest-bdd turns tags into
      markers). Tags do not touch the example rows, so the executable tables in
      `APPROACHES.md` stay in sync.
- [x] In `tests/conftest.py`, when `sys.platform == 'emscripten'`, skip `threads`
      items with that reason. On the desktop the marker changes nothing: `make test`
      runs the existing 150 plus the new asyncio tests.
- [x] Verify on the desktop: `make lint types test`; the existing 150 unchanged, the
      new tests passing, 0 suppressions.

### Phase 3 — the notebooks

- [x] First cell of each: `%pip install banking` (plus the libraries that notebook
      needs) and a print of `sys.version` and `sys.platform`, so every output shows
      which runtime produced it.
- [x] 01 to 04 follow the demo's section order and `APPROACHES.md`'s structure,
      importing from `banking` only. Short markdown cells in the repository
      register; the explanation stays in `APPROACHES.md`, linked, not duplicated.
- [x] 03 reproduces the overlap without threads: first the explicit `__enter__` of
      demo 6, then the two asyncio scenarios with top-level `await`, each run against
      all four binders and printed as one row per binder. A short markdown cell states
      why threads are absent and that `SerializedContext` gives no protection here,
      with one cell showing `threading.Thread(...).start()` raising, so the reason is
      demonstrated rather than asserted.
- [x] 05 runs the suite and prints passed / skipped / failed. Expected: every skip is
      a `threads` skip, nothing fails.
- [x] Notebooks are committed **with outputs cleared**, so a diff shows only source
      changes and no output claims anything that a fresh run has not produced.
      `nbstripout` as a pre-commit hook enforces it.
- [x] `ruff` lints and formats `.ipynb` by default; confirm `make lint` covers
      `notebooks/`.
- [x] Each notebook also runs on desktop CPython (`jupyter nbconvert --execute`, or
      `nbval`), so a change in `banking` that breaks a notebook fails locally too.

### Phase 4 — CI and deployment

- [x] `.github/workflows/lite.yml`: on push to `main`, `uv sync --group lite --frozen`,
      `make lite`, then `actions/upload-pages-artifact` and `actions/deploy-pages`.
- [x] If Phase 0 showed `pyodide venv` matches the browser, a job that runs the suite
      under Pyodide in Node on every push, so a regression in the browser runtime is
      caught without opening a browser.
- [ ] Enabling GitHub Pages (Settings → Pages → Source: GitHub Actions) is the
      user's action; the workflow cannot do it.
- [ ] Optional: a Binder link beside the JupyterLite one, for running the threaded
      tests in a real CPython kernel. Requires confirming that `repo2docker` can
      provide Python 3.14; if it cannot, drop this item.

### Phase 5 — documentation

- [x] `README.md`: a one-line link to the hosted notebooks, `make lite` and
      `make lite-serve` in the targets table, `lite/` and `notebooks/` in the layout.
- [x] `TOOLING.md`: what JupyterLite and the Pyodide kernel are for, how the wheel
      reaches the browser, the `lite` group, the Pages workflow, and the `threads`
      marker.
- [x] `APPROACHES.md`: one paragraph stating which findings reproduce under
      WebAssembly and how (asyncio in place of threads), and, under
      `SerializedContext`, that it serializes threads and not asyncio tasks, backed by
      `test_async_overlap.py`. No other change.
- [x] `CLAUDE.md`: the notebooks in the layout table, the `threads` marker and the
      asyncio limit of `SerializedContext` under Invariants, the new test count in
      Current state.

## Verification

The work is complete when:

1. `make lint types test` on the desktop: the existing 150 tests unchanged, the new
   asyncio tests passing, 0 suppressions.
2. `make lite && make lite-serve`: every notebook runs top to bottom in Chrome and
   Firefox from a cold cache.
3. Notebook 05 in the browser: no failures; every skip carries the `threads` reason;
   the skipped set equals the list from Phase 0.
4. The outputs of notebooks 01 to 03 match the corresponding demo output from a
   desktop run, character for character; the asyncio rows of notebook 03 match the
   same cells run on desktop CPython.
5. The Pages URL serves the same site the local build does.

## Risks

| Risk | Mitigation |
| --- | --- |
| `jupyterlite-pyodide-kernel` 0.8 is not yet on Pyodide 314 final, or the two lag each other | Phase 0 checks before anything is committed; the kernel config can point at a specific Pyodide URL |
| pydantic or SQLAlchemy in the Pyodide distribution differ from `uv.lock` and change a five-designs outcome | Print versions in notebook 04; report a difference as a finding in `APPROACHES.md`, do not paper over it |
| First load is slow (Pyodide plus packages, tens of MB) | Accepted; noted in the README link. Notebooks 01 to 03 need only `banking`, so they load fastest |
| `micropip` resolves pure-Python test dependencies to newer versions than `uv.lock` | Pin them in the install cell to the versions in `uv.lock` |
| Task interleaving in the browser's event loop differs from the desktop loop | The scenarios order themselves with `asyncio.Event`, not with sleep durations, so the interleaving is fixed by the code and not by timing |

## Open decisions for the user

1. **Hosting**: GitHub Pages from this repository (proposed), or no hosting and
   `make lite-serve` only.
2. **Test suite in the browser**: include notebook 05 and the `threads` marker
   (proposed), or keep the notebooks to the demo material and leave the suite
   desktop-only, which avoids touching `tests/` at all.
3. **Blog post**: whether part 2 links to the hosted notebooks. That edit belongs to
   the blog repository and is out of scope here.
4. **`SerializedContext` and asyncio**: either
   - **document it as a measured limit** (proposed): the Phase 2 test and the
     `APPROACHES.md` paragraph, with no new code in `banking/dci/`; or
   - **also add a fifth binder** built on `asyncio.Lock` and `async with`. That
     changes "four binders" throughout: `banking/dci/`, the contexts, the
     `role_binders.feature` table and its copy in `APPROACHES.md`, and the post.

   Either way, the post's decision table (the row that recommends
   `SerializedContext` for shared objects) needs a qualification for asynchronous
   applications. That edit is in the blog repository.

## Sources

- [Pyodide 314 release](https://blog.pyodide.org/posts/314-release)
- [JupyterLite 0.8 release](https://blog.jupyter.org/jupyterlite-0-8-is-released-0c89c4200f79)
- [jupyterlite-pyodide-kernel on PyPI](https://pypi.org/project/jupyterlite-pyodide-kernel/)
- [Pyodide ABI flags: no pthreads support](https://pyodide.org/en/0.29.4/development/abi/flags.html)
- [PEP 776 – Emscripten support](https://peps.python.org/pep-0776/)
- [PyScript FAQ: SharedArrayBuffer and cross-origin isolation](https://docs.pyscript.net/latest/faq)
