# Approaches — the same transfer, implemented every way it can be

One use case, moving money between two accounts, implemented repeatedly on
purpose, along two axes:

* **Four ways to bind a role** — the DCI mechanism itself, four times, differing in how the role is attached. This is the axis the repository was built to measure.
* **Five ways to write the transfer** — DCI against the designs it argues with, including one that is not a straw man.

Each one is described here together with where it fails and what those failures
mean. [README.md](README.md) introduces the mechanism; how to run any of this is
in [TOOLING.md](TOOLING.md).

# Four ways to bind a role

`banking/dci/` provides four contexts, one binder per module. All four derive
from `BaseContext` and share the lifecycle, the `ContextVar` lookup,
all-or-nothing binding and the non-re-entrancy guard. They differ in how a role
is attached.

## `Context` — the role mixed into the object's class

`banking/dci/class_binding.py`. Binds by reassigning the object's class:
`obj.__class__ = _class_with_role(...)`. The default.

**Where it fails.** `tests/unit/test_limits.py` asserts these rather than
describing them, so a future Python release that changes one of them fails the
suite instead of leaving the documentation quietly wrong.

* **`__slots__`** — `__class__` may only be reassigned between classes with the same object layout, and slots change the layout: `TypeError: object layout differs`. The common explanation, that slots remove the object's `__dict__`, is not sufficient: an empty `__slots__ = ()` removes nothing and still makes the reassignment illegal, which is how the declaratively mapped ORM entity is caught without anyone choosing slots. The exact CPython layout rule is confirmed behaviourally, not explained.
* **Frozen dataclasses** — the same outcome by a different route. A frozen dataclass rejects every `__setattr__`, and `__class__` is an attribute like any other. This is why `Money` is a plain class.
* **Two live contexts over one object, wanting the same role** — `__class__` is state of the *object*, and DCI uses it as though it were state of the *context*. The second context receives `TypeError: cannot create a consistent MRO`. There is a threaded test for it.
* **Two live contexts over one object, wanting different roles** — the same defect without the error. An account paying one transfer out while a second pays into it needs `SourceAccount` and `DestinationAccount`, which stack into a class with a consistent MRO, so both contexts bind. Each then restores the class it found on the way in, which is correct only while the two nest: two requests that overlap without nesting leave the account playing the first one's role permanently, with nothing raised anywhere. The MRO error is what makes the same-role case survivable, and this case does not have it. Asserted in `tests/unit/test_limits.py`, down to the later transfer that inherits the error.
* **The synthesized class is not in any source file** — `type(a).__name__` is `Account@SourceAccount`, which no search will find, no IDE will complete, and no type checker can be shown.

## `TransparentContext` — the synthesized class renamed

`banking/dci/transparent.py`. As `Context`, with the synthesized class
**renamed** to the data class it was built over. The rename is what does the
work, not the metaclass: `__name__` feeds CPython's `tp_name`, whereas a
`__name__` property on the metaclass changes what attribute access reports and
leaves the error messages unchanged.

**It answers the unopenable class name, cosmetically.** Error messages report
`Account`, and the underlying classes remain available on the class itself
(`type(obj).__dci_role__`, and a `repr` that reports both). The cost is that an
object whose type prints as `Account` carries a `transfer` method that `Account`
does not define, so searching the source for it finds nothing. Every other
failure above is unchanged.

## `SerializedContext` — the participants locked

`banking/dci/serialized.py`. As `Context`, with every participant **locked** for
the duration of the use case, so two contexts over the same object take turns.
Locks are acquired in `id()` order, which makes the opposite-direction deadlock
impossible.

**It answers the collision**, and what the lock covers is worth stating. `self.balance
= self.balance - amount` is a read, a subtraction and a write; two threads
interleaving there lose an update whether or not roles are involved. The lock is
therefore not a cost DCI introduces — it is one the domain already required, and
would have paid as a `SELECT ... FOR UPDATE` once the account lived in a
database. What role binding adds is that the same race surfaces as a `TypeError`
rather than a silent lost update. `tests/unit/test_serialized_roles.py` measures
the four properties that have to hold: the collision is gone under real threads,
the lost update is gone, transfers sharing no participant still run in parallel
(measured on the clock), and opposite-direction transfers between the same two
accounts do not deadlock.

## `InstanceContext` — the role written into the instance

`banking/dci/instance.py`. Binds by writing the role's methods into the object's
`__dict__` as bound methods, and removing them on exit. No class is synthesized,
so `type(obj)` remains `Account` throughout.

**It answers frozen dataclasses and declaratively mapped ORM entities**, because
it never touches `__class__` and so is unaffected by layout. It writes through
`object.__setattr__`, which the freeze cannot refuse — appropriately, since a
role is not domain state. It answers the unopenable class name as well, and more
completely than `TransparentContext` does, since there is no synthesized class
to name.

**It answers the silent leak as well.** `_bind` records the names it wrote and
`_strip` removes exactly those, so two contexts wanting different roles of one
account — the case the class binders bind without complaint and then restore
wrongly — can leave in any order and give the object back holding nothing.
`test_instance_roles.py::test_two_contexts_wanting_different_roles_give_the_object_back_intact`
asserts it against the class-bound version of the same overlap.

**Why pickling then fails on load.** Binding puts a bound method in the
instance dictionary, so `alice.__dict__['transfer']` is `<bound method
SourceAccount.transfer of Account('Alice', 1000)>`. CPython knows how to pickle
a bound method, and it does it *by reference*: `method.__reduce__()` returns
`(getattr, (alice, 'transfer'))` — "call `getattr` on this object with this
name". Nothing about that is unserializable, so `dumps` succeeds and hands back
bytes.

The recipe is circular, and only load discovers it. The value stored under
`transfer` is an instruction to read `transfer` off the account. At dump time
that reads back fine, because the attribute is there. At load time pickle
rebuilds the account first and then reconstructs its state, so it calls
`getattr(account, 'transfer')` on an account that does not have the attribute
yet — and never will, because the only thing that would have supplied it is the
value currently being reconstructed. The result is `AttributeError: 'Account'
object has no attribute 'transfer'`.

Two things make this worse than a refusal. The failure happens in whatever
process later reads the cache, the queue or the session, not in the one that
serialized a participant mid-use-case; and its traceback names `getattr` and an
ordinary `Account`, saying nothing about roles or contexts.
`test_instance_roles.py::test_neither_binder_survives_pickling_but_they_fail_differently`
asserts both halves, and
`test_instance_roles.py::test_the_bytes_fail_in_whichever_process_reads_them`
hands the bytes to a second interpreter, so the process boundary the cost is
about is crossed rather than described.

**Why a role cannot contribute a special method.** Python resolves dunders on
the *type*, not on the instance. `a < b` does not look in `a.__dict__`; it goes
straight to `type(a).__lt__`. So a role that makes its player comparable,
iterable or callable works under `Context`, where the role is mixed into a real
class, and cannot work here, where the method lands in the instance dictionary
the operator never consults.

The method is not merely ineffective, it is ineffective *invisibly*. Written
into `Money(5).__dict__['__lt__']`, `amount.__lt__(Money(1))` called by name
answers `True`, while `Money(5) < Money(1)` answers `False` — `Money.__lt__`
wins, because that is the only one the operator ever looks up. `_role_methods`
therefore declines to bind dunders at all: a role method that could never run
is better left unbound than installed and silently skipped, and the table reads
*impossible* rather than *broken*.
`test_instance_roles.py::test_a_role_cannot_contribute_a_dunder` measures both
halves of that contradiction.

## Two guards shared by all four

Neither of these has anything to do with roles. Any context manager acquiring
several resources must unwind a partial acquisition, and any context manager
holding a single token is non-reentrant. Both are closed once in `BaseContext`,
so all four binders inherit them.

**Binding is all-or-nothing.** `__enter__` sets the ContextVar first, then binds
the roles one at a time. Suppose the destination account is a slotted class:
role 1 binds, role 2 raises `TypeError`. The exception leaves `__enter__`, so
the `with` body never runs — and Python only calls `__exit__` when `__enter__`
returned successfully. Without the guard nothing would ever clean up: the
ContextVar would still point at that half-built transfer for the rest of the
thread's life, and the source account would stay an `Account@SourceAccount`
permanently. The damage lands later and elsewhere — a role in some unrelated
operation calls `context()` and receives a stale transfer instead of
`LookupError`. On a thread pool, that crosses requests. The guard is the
`except BaseException: self._release(); raise` that unwinds exactly what bound
and pops the variable.

**A context is not re-entrant.** `_token` is one slot. Entering twice overwrites
it, and the outer `__exit__` then resets a token the inner exit already spent —
CPython answers `ValueError: <Token …> has already been used once`, which names
neither the context nor the class. This is a realistic mistake because
`execute()` is itself `with self:`, so calling `ctx.execute()` from inside
`with ctx:` triggers it. That is precisely why `run_script()` exists as a
separate entry point. The guard raises `RuntimeError('… is already running: a
context is not re-entrant')` instead.

Both are asserted for every binder:
`test_roles.py::test_a_failed_bind_leaves_nothing_behind`,
`::test_a_context_refuses_to_be_entered_twice`, and two `Scenario Outline`s in
`role_binders.feature`.

## The four compared

Each context in `banking/contexts/money_transfer.py` combines a binder with the
single use case, so the roles, the participants and the script are written once:

```python
class SerializedMoneyTransferContext(SerializedContext, MoneyTransferContext):
    """The same transfer, with all three participants locked for the duration."""
```

| | `Context` | `Transparent` | `Serialized` | `Instance` |
| --- | :---: | :---: | :---: | :---: |
| plain Python class | ✅ | ✅ | ✅ | ✅ |
| `@dataclass(frozen=True)` | ❌ | ❌ | ❌ | ✅ |
| declaratively mapped ORM entity | ❌ | ❌ | ❌ | ✅ |
| `__slots__` / attrs `@define` | ❌ | ❌ | ❌ | ❌ |
| `type(obj).__name__` reports | `Account@SourceAccount` | `Account` | `Account@SourceAccount` | `Account` |
| error messages name | `Account@SourceAccount` | `Account` | `Account@SourceAccount` | `Account` |
| `pickle` while bound | ❌ refuses | ❌ refuses | ❌ refuses | ⚠️ **fails on load** |
| two live contexts, same role | ❌ MRO error | ❌ MRO error | ✅ **serialized** \* | ❌ refuses |
| two live contexts, different roles | ❌ **leaks, silently** | ❌ **leaks, silently** | ✅ **serialized** † | ✅ **intact** |
| a role contributing a dunder | ✅ | ✅ | ✅ | ❌ not possible |

\* **Across threads**, which is the contended case. A single thread that opens two contexts over one object still receives the MRO error, because the lock is an `RLock` and re-entrant to its owner. That is the correct outcome: one thread inside two live contexts over one object is a defect, not contention, so there is nothing to wait for.

† **Across threads** as well, and here the single-thread case is not correct, only unreported. Nothing refuses two different roles, so one thread that opens both contexts is never made to wait and reaches the same leak as `Context`. Both halves are asserted in `tests/unit/test_serialized_roles.py`.

**This table is executable.** `tests/acceptance/features/role_binders.feature`
contains every cell as an example row, so a Python release that changes one
answer fails exactly that row.

Three rows need explanation.

**Two live contexts, same role.** The three class binders write to state
belonging to the *object* — its class — so any per-object mechanism inherits the
problem. `SerializedContext` does not avoid it; it prevents two contexts from
holding the object at the same time, which is a different thing and the only
approach that works. `InstanceContext` refuses instead: `_bind` will not write
over a name the object already has, so the second context raises `RuntimeError`
where the class binders raise an MRO error. Three of the four therefore fail at
the scene and in the context that caused it, and only the locking one lets both
transfers complete.

The row measures *threads*, which is the contended case. One thread opening two
contexts over one object is a defect rather than contention, and all four refuse
it — `SerializedContext` included, since its `RLock` is re-entrant to the thread
already holding it. Both situations are example rows in `role_binders.feature`,
under *Two transfers out of one account* opened by one thread and served by two.

**Two live contexts, different roles.** The worse case, and the one an MRO error
gives no warning of. `SourceAccount` and `DestinationAccount` stack into a class
with a consistent MRO, so under the class binders both contexts bind. What is
wrong is what each context puts back: the class it found on the way in. Two
requests that overlap without nesting — the first to open is the first to close
— therefore leave the account playing `SourceAccount` outside every context, and
the next transfer out of it stacks that role on itself and fails with the MRO
error of the row above, arbitrarily later and in a request that did nothing
wrong.

Which of the two overlapping transfers pays for it depends on where the first
exit falls. If both have run their scripts by then, both complete with correct
balances and the leak is all that is left. If the second is still mid-script,
the first exit takes `DestinationAccount` away from underneath it and that
transfer dies on a missing `receive`, with nothing in the message about roles,
contexts or the other request.
`tests/unit/test_limits.py` asserts both timings, the second one across two
threads because a single thread reaches a `LookupError` on the popped
`ContextVar` before it can get that far.

`InstanceContext` is unaffected, because `_bind` records the names it wrote and
`_strip` removes exactly those: the order the two contexts leave in cannot
matter. `SerializedContext` closes it the way it closes the row above, by
keeping the two from overlapping at all, and with the same qualification —
across threads, not within one.

The `role_binders.feature` scenario is *One account paying a transfer out while
another pays into it*.

**Pickle.** No binder survives a round trip. They differ in *when* the attempt
fails. `Context` raises at `dumps`, in the process that serialized a
participant mid-use-case, because the synthesized class exists in no module.
`InstanceContext` accepts the `dumps` and writes bytes that raise at `loads`,
in whatever process reads the cache or the queue afterwards. Why those bytes
cannot be loaded is explained under *Why pickling then fails on load*, in the
`InstanceContext` section.

## Whether a persisted object can play a role

`tests/integration/test_orm_roles.py` answers the question the unit tests
cannot: can a *persisted* domain object play a role? It needs a real database,
which is why it is an integration test. Measured on Python 3.14:

| How the domain object is written | `Context` (class binding) | `InstanceContext` |
| --- | --- | :---: |
| **SQLAlchemy, imperative mapping** (`map_imperatively`) | ✅ works | ✅ |
| pydantic v2 `BaseModel` | ✅ works | ✅ |
| **SQLAlchemy, declarative** (`class Account(Base)`) | ❌ `TypeError: object layout differs` | ✅ |
| `@dataclass(frozen=True)` | ❌ `cannot assign to field '__class__'` | ✅ |
| attrs `@define` (`slots=True` is the default) | ❌ same limit | ❌ same limit |

Declarative mapping fails under class binding because `DeclarativeBase`
contributes `__slots__ = ()`, and mixing a plain role class over that produces a
layout CPython refuses to reassign. Nobody selected slots; they arrive with the
base class.

Imperative mapping works because the domain class remains plain Python: the
table is described separately and the class learns nothing. The test maps
`banking.data.account.Account` itself, unmodified — all the adaptation happens in
a `TypeDecorator` on the infrastructure side. The object loads from the
database, plays its part, is modified through the role, releases the role, and
the change is persisted.

The second column narrows that finding rather than contradicting it.
`InstanceContext` can put a `class Account(Base)` entity into a role, round trip
included, because it never touches `__class__`. What it cannot do is the two
things class binding provides: a role that contributes a special method, and an
immediate failure when two contexts collide rather than a silent one. So
imperative mapping is what makes DCI available *with class binding*; it is not
the only way to get a persisted object into a role.

The architectural conclusion holds either way: **DCI works when domain objects
are plain Python objects with no knowledge of the infrastructure.** That is what
DCI asks for in any case — Data is meant to be *barely smart data* — and what DDD
and Clean Architecture ask for on independent grounds. The mechanism does not
penalise persistence; it penalises letting the persistence framework into the
domain class.

# Five ways to write the transfer

The four above vary the *mechanism* and hold the design fixed. These five vary
the design. All of them move the money.

| | 1. fat account | 2. anemic + service | 3. DCI | 4. wrapper | 5. service |
| --- | :---: | :---: | :---: | :---: | :---: |
| The use case is an object | ❌ | ❌ | ✅ | ✅ | ✅ |
| The roles are named | ❌ | ❌ | ✅ | ⚠️ source only | ✅ all three |
| The script is in one place | ❌ | ✅ | ✅ | ✅ | ✅ |
| The data objects stay minimal | ❌ | ⚠️ minimal but manipulated | ✅ | ✅ | ✅ |
| The object **is** the role | — | — | ✅ | ❌ | ❌ |
| The object keeps its identity — `is`, `isinstance`, `hash` | ✅ | ✅ | ✅ | ❌ | ⚠️ lost, but never leaves `transfer()` |
| Works with `__slots__` / frozen / declarative ORM | ✅ | ✅ | ❌ | ✅ | ✅ |
| Two concurrent requests both succeed | ✅ | ✅ | ⚠️ with locks | ✅ | ✅ |
| The type checker reads it without a `cast` | ✅ | ✅ | ❌ | ✅ | ✅ |

The two identity rows say different things, and read together they are the
argument. Designs 1 and 2 keep identity because nothing ever stands in for the
account — but they have no roles at all. Designs 4 and 5 get roles by paying the
Decorator price: the object playing the part is not the account, so comparing it
by identity, hashing it or passing it to `isinstance` all answer wrongly. Design
3 is the only one that has both.

The **top four rows are design claims** about how the code reads; the five below
them are measured. The claims are arguable, which is why all five
implementations are in the package rather than only in prose: a reader who
disagrees with a cell can open the file it refers to.

### 1. The account that knows too much

`banking/alternatives/fat_account.py` → `FatAccount`, called as
`source.transfer_to(destination, amount)`. Readable at first, and over time
`Account` acquires knowledge of fees, daily limits and garnishments. The use
case has been absorbed into the entity.

### 2. The anemic account and the service

`banking/alternatives/anemic_service.py` → `AnemicAccount` + `TransferService`. The corrective
reaction to the first, and the common form in line-of-business systems. The
account is small again but does nothing, and the service manipulates its
attributes from outside. There are no roles: "source" and "destination" are
parameter names that cease to exist when the function returns.

### 3. DCI, with role binding

`banking/dci.py` + `banking/roles/` + `banking/contexts/`. The use case is an
object, the roles are named objects, the script is in one place, and `Account`
learns nothing — and the object **is** the role, with its `id()` and its
`isinstance` unchanged. It is the only one of the five that achieves that, and
the only one that fails on `__slots__`, on two live contexts and on the type
checker.

### 4. The role as a wrapper

`banking/alternatives/role_as_wrapper.py` → `SourceWrapper` + `WrappedTransfer`. The obvious
response to the limitations above: implement the role as a wrapper.

```python
class SourceWrapper:
    def __init__(self, account: AccountLike, ctx: WrappedTransfer) -> None:
        self._account = account
        self._ctx = ctx

    def __getattr__(self, name: str) -> Any:
        return getattr(self._account, name)

    def transfer(self, amount: Money) -> None:
        if self._account.balance < amount:
            raise InsufficientFundsError(self._account.holder)
        self._account.debit(amount)
        self._ctx.destination.credit(amount)
```

This works, is unaffected by `__slots__`, has no concurrency problem, type
checks, and needs no explanation to read. But the wrapper **is not** the
account: storing it, comparing it by identity, passing it to code that calls
`isinstance`, or using it in a `set` or as a dictionary key all behave
incorrectly. This is the identity problem of the Decorator pattern, which
Reenskaug and Coplien cite when they observe that most GoF patterns break
object identity to achieve their effect.

What is lost is the property that distinguished DCI from passing the object to
a function: in DCI the object plays the role, whereas here the object is held
inside another object that plays it.

### 5. The service

`banking/services/money_transfer.py`. The version the other four omit. Comparing
DCI against the fat account, the anemic service and a `__getattr__` presenting
itself as an account is comparing it against three designs nobody defends. The
comparison that matters is against a service written by someone who understood
DCI and chose not to use the mechanism.

It keeps almost everything DCI provides. The use case is still an object
(`TransferRoles`, created per transfer). The roles are still named objects,
`TransferAmountRole` included, so the third role survives. A role still reaches
its peers through the roles object rather than holding another participant's
data. The script is still in one place, and the role bodies are nearly
identical to the DCI ones, because narrow forwarding properties let a role
write `self.balance` and `self.debit(...)`. `Account` is unchanged.

One thing is given up: the data object never becomes the role, so
`isinstance(role, Account)` is `False`. That is the same identity loss as the
wrapper, but contained, and the difference is the discipline around it. There
is no `__getattr__` catch-all presenting the role as the account, only the
members the role uses; and the role objects are strictly internal, built inside
`transfer()`, never returned, stored, compared, or used as a key. A wrapper
that cannot leave the method that built it cannot be mistaken for the object it
wraps.

In exchange, the service avoids every limitation the mechanism has. It transfers
between all five domain-object styles, including the three class binding refuses
outright; two concurrent transfers over one account both succeed where class
binding raises an MRO error; and both type checkers read it with no casts.
