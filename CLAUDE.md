# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A DCI (Data, Context, Interaction) implementation in Python, and the companion code for two blog posts. It is not a library anyone installs: it exists to **demonstrate DCI as an object-oriented style of programming, using the resources Python 3.14 provides, and to measure how far those resources carry it**. That framing drives most of the decisions below: the style is the subject, the language is the second subject, and the failures are the boundary of what the language supplies rather than a verdict on the style. The tests assert failures deliberately, and every claim in the documentation is backed by a passing assertion — with one stated exception, the top four rows of the five-designs table in `APPROACHES.md`, which are design judgements and are labelled as such.

The prose is split across three files, and an edit should land in the right one:

| File | Holds |
| --- | --- |
| `README.md` | what the mechanism is, the `make` targets, and the layout. It introduces; it does not measure |
| `APPROACHES.md` | the four binders and the five designs, each with where it fails and what those failures mean, plus both comparison tables and the persistence finding |
| `TOOLING.md` | prerequisites, what each tool is for, `--frozen` for one-off commands, CI, dependency updates, building a wheel |

Each binder is described in `APPROACHES.md` alongside the failures it has and the
failure it answers.

The posts live in a separate repository:

- Part 1 (background): `content/es/posts/2026-08-04-dci-data-context-interaction-reenskaug/index.md`
- Part 2 (this code): `content/es/posts/2026-08-05-dci-en-python-roles-en-runtime/index.md`

under `C:/Users/cesar/cesar/blog/katra/CesarBallardini.github.io/`.

## Commands

Every task goes through the Makefile. **`README.md` holds the full list of targets**, and `make` with no target prints the same list from the Makefile itself. The two used most often here are `make lint types test` and `make demo`.

A single test, or a single parametrized case:

```bash
uv run --frozen pytest tests/unit/test_limits.py::test_slots_make_role_binding_illegal
uv run --frozen pytest "tests/unit/test_money_transfer_service.py::test_and_dci_refuses_those_same_three[FrozenAccount-cannot assign to field '__class__']"
```

Use `uv run --frozen` for one-off commands so that none of them rewrites `uv.lock`. Python 3.14, `requires-python = ">=3.14"`, matching the sibling `localenv-python` scaffold this repository's tooling comes from.

## Architecture

**The package is `banking`.** DCI is the *mechanism* the domain is written with, so it is a package (`banking/dci/`) inside the domain package rather than the top-level package itself.

The layout follows the three letters, plus two packages for comparison:

| Module | Contents |
| --- | --- |
| `banking/dci/` | The mechanism, one binder per module: `base.py` (`context()`, `BaseContext`), `class_binding.py`, `transparent.py`, `serialized.py`, `instance.py`. `__init__.py` re-exports the public names, so `from banking.dci import Context` is unchanged |
| `banking/data/` | `Account`, `Money` — minimal, stable, with no knowledge of transfers |
| `banking/roles/` | `SourceAccount`, `DestinationAccount`, `TransferAmount` |
| `banking/contexts/` | The use case, reified once per binder |
| `banking/services/` | The same use case as a service, without the mechanism |
| `banking/alternatives/` | The two designs DCI argues against, plus the role-as-wrapper, one per module: `fat_account.py`, `anemic_service.py`, `role_as_wrapper.py` |

### Things that cannot be inferred from one file

**There are four binders, not one.** `Context` (reassigns `__class__`), `TransparentContext` (the same, with the synthesized class renamed to the data class), `SerializedContext` (the same, with participants locked) and `InstanceContext` (writes the role's methods into the instance). They share `BaseContext`; only `SerializedContext` overrides `__enter__` and `__exit__` as well as `_bind`. `APPROACHES.md` compares them cell by cell.

**Roles are never instantiated and inherit from nothing.** They are classes written to be mixed into a data object's class at runtime. Each declares the protocol it requires of its player under `if TYPE_CHECKING:`; that block does not exist at runtime, and the synthesized `Account@SourceAccount` resolves those members on the data class.

**A role reaches its peers through the context, never by reference.** A role calls `context(_RunningTransfer)`, the protocol declared at the bottom of `roles/money_transfer.py`. That protocol exists so roles never import concrete contexts: a context knows its roles, a role does not know its contexts. Unlike the protocols the role classes declare for their own players, `_RunningTransfer` exists **at runtime**, because it is passed as a value.

**`context()` is generic, and that is what removed two casts.** It has two overloads: no argument returns a `BaseContext`, and `context(SomeProtocol)` returns that protocol. The argument is deliberately not inspected — checking it would mean an `isinstance` against a protocol on every role call — it states what the caller requires, for the type checker. Prefer this to a `cast` wherever a generic parameter can carry the fact.

**There are three roles, and the amount is one of them.** `TransferAmount` is why `SourceAccount.transfer()` takes **no parameters**: the amount is a participant with a part of its own, not an argument passed between functions.

**`AccountLike` (in `data/account.py`) is load-bearing.** It is the structural protocol every account-shaped object satisfies. Its members are read-only properties, and `debit`/`credit` take the amount **positional-only** (`/`); without that, a conforming class would have to name the parameter `amount` exactly. This protocol is why the tests can pass the context slotted, attrs, pydantic and ORM-mapped objects with no suppressions.

**`BaseContext` carries two guards.** Binding is all-or-nothing (a failed `__enter__` unwinds and pops the ContextVar, otherwise a half-entered context stays installed for the rest of the thread's life), and a context is not re-entrant (a second `__enter__` would overwrite the first's token). `run_script()` is separate from `execute()` so that a caller already inside the context can run the interaction without re-entering.

**`InstanceContext` carries a third guard of its own.** `_bind` refuses to write over a name the object already has, raising `RuntimeError` rather than overwriting. It closes two things at once: a second live context is turned away at the scene instead of corrupting the first, and a domain object that happens to own an attribute a role also defines does not lose it to `_strip` on the way out. The check is what keeps `_strip` honest — a context can only ever remove names it installed itself. It is a check and not a lock: two threads entering at the same instant can still both find the name absent, and closing that window is what `SerializedContext` is for.

**Two implementations of one use case, deliberately.** `contexts/money_transfer.py` and `services/money_transfer.py` are meant to be compared directly. The service keeps the reified use case, the three named roles, the peer-through-context rule and the minimal data objects; it gives up one thing, in that the object does not *become* the role. It stays distinguishable from a wrapper by having no `__getattr__` catch-all and never letting a role object escape `transfer()`.

## Invariants

**Zero type suppressions.** No `# type: ignore`, no `# pyright: ignore`. Both checkers must report **0 errors and 0 suppressed**. When a diagnostic appears, fix the cause; usually the answer is to widen a signature to a protocol rather than silence it. `typing.cast` is allowed where it states a runtime fact a checker cannot see (the synthesized role class; SQLAlchemy's `Mapped[str]`), and each one carries a comment explaining why.

**`Account` and `Money` must stay plain Python classes.** Neither `__slots__` nor `@dataclass(frozen=True)`: both make `__class__` reassignment illegal, so such a class cannot play a role under `Context`, `TransparentContext` or `SerializedContext`. `InstanceContext` does accept a frozen dataclass, but it is not the default and the demo and most tests use class binding, so converting either class will break the suite in ways that are hard to read.

**`tests/unit/test_limits.py` asserts failures deliberately.** Those tests are expected to raise. If one starts failing, a Python version has changed something: investigate rather than repairing the test.

**Integration tests instrument `Account` globally.** `map_imperatively` mutates the class; the `mapped_domain` fixture calls `clear_mappers()` on teardown. Removing that teardown makes unrelated tests fail depending on ordering.

**`clear_mappers()` is global — never call it from a second place.** It un-instruments *every* mapped class in the process, including `test_orm_roles.py`'s module-level ones, which are mapped at import time. The acceptance fixture in `tests/acceptance/steps/test_role_binding_steps.py` maps its own classes and therefore disposes **its own registries** instead. Two callers of `clear_mappers()` make the suite order-dependent, and acceptance sorts before integration, so the failure is real rather than theoretical.

**The comparison tables are executable.** `tests/acceptance/features/role_binding.feature` covers which domain objects can play a role and `role_binders.feature` covers the four binders cell by cell. Both tables live in `APPROACHES.md`, so neither can drift. Changing a table means changing an example row, and the reverse.

**The whole repo is in English** — code, comments, docstrings, tests, docs and program output, `demo/dci_demo.py`'s section titles included.

**`demo/dci_demo.py` output feeds the blog post.** The post quotes ten console blocks, all verbatim from a real run. Changing what the demo prints means regenerating those blocks from a fresh run: paste from the run, never hand-edit, and never re-wrap a long line. Several blocks already contain lines over 130 characters, and keeping every block literal is what makes verification a plain substring comparison. The demo's section titles are printed output rather than comments, so this applies to them too.

**Docs describe the code as it is.** No "used to", no "changed from", no account of how a decision was reached: a reader wants the current state and the reason for it, not the history. Prior versions of *other* projects (Molenaar's `roles`, the blog post's own snippets) are legitimate as references, because there the history is the subject.

**Register: simple, professional, descriptive English.** State what the code does and why. No rhetorical questions, no second person, no metaphors doing the work of an explanation ("trap", "wall", "magic", "at three in the morning", "beats"), no editorialising about what a reader will feel. Comparatives are fine when factual ("fails on load rather than on dump"); they are not fine as slogans. This applies to the repository only — the blog post keeps its own voice.

**Conventions:** person names use the Alice / Bob / Charlie / Dave set. `Money` is an integer count of minor units plus a currency label, with no floats. ruff uses single quotes and a line length of 119.

**Each tool keeps its own config file.** `pytest.ini` (markers, `--strict-markers`, and one warning filter scoped to a single deprecation in `gherkin-official`), `ruff.toml`, `pyrightconfig.json`, `pyrefly.toml`, `bandit.yaml`. `pyproject.toml` holds the project metadata, the build backend and the dependency groups, and no tool configuration.

## Current state

The code is complete and green: ruff clean, pyright 0 errors, pyrefly 0 errors **and 0 suppressed**, 137 tests passing, demo exits 0, security scans clean.

**The blog post is also complete.** All five phases of the plan, and the three later findings, have been applied: the console blocks, the code blocks and the diagram are synchronized with the repository; the four breakages are written up, including `@dataclass(frozen=True)` and `attrs`; the two `BaseContext` guards are explained; the four binders have their own section with the comparison table; the persistence finding has its own section; the five designs are compared; Feathers' objection is answered using the third role; and the arc back to part 1 is closed from both ends.

A dated audit, the phase plan and a paste-ready appendix live at:

`content/es/posts/2026-08-05-dci-en-python-roles-en-runtime/2026-08-05-draft-doc.md`

Read the audit at the top before touching either file, and re-audit rather than trusting it if the post has moved since.

## Open questions

Two decisions remain, and both are the user's to make. Do not act on either
without being asked. What follows is what each one would involve.

### Q1 — Is the post too long, and if so what goes?

Measured on the current text: **7,730 words of body prose**, 1,123 in 16
footnotes, 345 lines of code — roughly an hour of reading. Repetition has
already been removed and verified: no two sentences in different sections
exceed 0.53 similarity, so there is nothing left to cut on those grounds.
Anything further removes material that is doing work.

| Section | Words |
| --- | ---: |
| La transferencia, tres veces | 1430 |
| Y acá viene el problema | 1147 |
| El veredicto | 1126 |
| Cinco maneras de escribir la misma transferencia | 1082 |
| Un paréntesis: la librería que hay | 1002 |
| Cuatro maneras de prestar un rol | 728 |
| La pregunta que decide si esto se puede usar | 547 |
| La maquinaria, en veinticinco líneas | 445 |
| Lo que se gana | 223 |

**Option A — leave it.** The distribution is even and no section is oversized
for its job. This is the current state and needs no work.

**Option B — shorten the Molenaar digression** (1,002 words, 13%). It is the
only section the post itself labels a digression, and the argument survives
without it. Reducing it to the version table and two paragraphs recovers about
700 words. Against: it is the only part of the post that no other article on
DCI has, and its subsection comparing Molenaar's implementation with this one
is original material.

**Option C — split into two posts** at the seam before "Cuatro maneras de
prestar un rol". That divides cleanly: 3,245 words of *the mechanism and where
it fails*, and 4,485 words of *what can be done about it, and the verdict*. Two
posts of about half an hour each, each with a complete argument. If this is
chosen, the work is: a new bundle and slug, moving the second half, giving each
half its own opening and close, re-pointing the cross-links in part 1 (four of
them, all by slug with generic anchor text, so they need re-targeting), and
re-running the console-block verification against the new file.

Part F of the draft document holds the same analysis in Spanish.

### Q2 — The CPython layout rule is confirmed but not explained

`DeclarativeBase` contributes `__slots__ = ()`, and mixing a plain role class
over that produces a layout CPython refuses to reassign. The *behaviour* is
asserted in `tests/integration/test_orm_roles.py` and reproduced on demand. The
*rule* — why an empty `__slots__` changes the solid base when it adds no
storage — has not been traced through `Objects/typeobject.c`.

Both `APPROACHES.md` and the post say so in as many words, which is the honest
position and requires no change. **Do not assert the mechanism anywhere without
tracing it first.** If it is ever traced, the places to update are the
`__slots__` bullet under `Context` in `APPROACHES.md`, the paragraph on
declarative mapping in its persistence section, the equivalent paragraph in the
post, and footnote `[^layout]` there.
