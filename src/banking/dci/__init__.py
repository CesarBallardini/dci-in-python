"""The DCI mechanism: roles lent to live objects for the duration of a context.

This package contains the machinery and nothing else. It has no knowledge of
accounts or transfers: it knows how to attach a role's behaviour to an object
while a context runs, and how to remove it when the context ends. The domain
lives in `banking.data`, the roles in `banking.roles`, and the use cases in
`banking.contexts`.

Four contexts are provided, one binder per module. All four derive from
`BaseContext` and share the lifecycle, the `ContextVar` lookup and the two
guards described there; they differ in how a role is bound, which is the one
method each module supplies.

===========================  ==============================================
module                       contents
===========================  ==============================================
`banking.dci.base`           `context()`, `BaseContext`
`banking.dci.class_binding`  `Context`
`banking.dci.transparent`    `RoleClass`, `TransparentContext`
`banking.dci.serialized`     `SerializedContext`
`banking.dci.instance`       `InstanceContext`
===========================  ==============================================

`Context` -- bind by reassigning the object's class. The operative line is::

    obj.__class__ = _class_with_role(obj.__class__, role)

Python allows the class of a live instance to be reassigned, so entering
synthesizes a subclass that mixes the role over the object's own class
(``Account@SourceAccount``) and installs it; leaving restores the original. The
object is neither wrapped nor copied: it keeps its ``id()`` and remains an
``Account`` for ``isinstance``, so the rest of the system sees no change.

`TransparentContext` -- as `Context`, with the synthesized class carrying the
name of the data class it was built over, so error messages and tracebacks do
not name a class that exists in no source file. Labelling only; the binding is
identical.

`SerializedContext` -- as `Context`, with every participant locked for the
duration of the use case. Two contexts cannot share an object's ``__class__``,
so they take turns instead of colliding. This is the only one of the four that
overrides `__enter__` and `__exit__` as well as `_bind`.

`InstanceContext` -- bind by writing the role's methods into the object's
``__dict__`` as bound methods, and deleting them on exit. No class is
synthesized, so ``type(obj)`` is unchanged throughout.

None of the four replaces the others; each fails where the others do not. The
table below is asserted by `tests/unit/test_limits.py`,
`test_transparent_roles.py`, `test_serialized_roles.py` and
`test_instance_roles.py`:

===========================  ============  =============  ============  =================
what                         `Context`     `Transparent`  `Serialized`  `InstanceContext`
===========================  ============  =============  ============  =================
plain class                  works         works          works         works
``@dataclass(frozen=True)``  refuses       refuses        refuses       works
declaratively mapped ORM     refuses       refuses        refuses       works
``__slots__`` / attrs        refuses       refuses        refuses       refuses
``type(obj).__name__``       ``Acc@Src``   ``Account``    ``Acc@Src``   ``Account``
error messages name          ``Acc@Src``   ``Account``    ``Acc@Src``   ``Account``
``pickle`` while bound       refuses       refuses        refuses       **breaks late**
two live contexts            MRO error     MRO error      **queue** [#]_  refuses
a role adding a dunder       works         works          works         impossible
===========================  ============  =============  ============  =================

.. [#] Across *threads*, which is the contended case. A single thread that
   opens two contexts over one object still receives the MRO error, because the
   lock is an `RLock` and re-entrant to its owner. That is the correct outcome:
   one thread inside two live contexts over one object is a defect, not
   contention, so there is nothing to wait for.

Two rows need explanation.

**Two live contexts.** The three class binders write to state that belongs to
the *object* -- its class -- and the object is shared, so any per-object
mechanism inherits the problem. `SerializedContext` does not avoid it; it
prevents two contexts from holding the object at the same time, which is a
different thing and the only approach that works. `InstanceContext` refuses
instead: `_bind` will not write over a name the object already has, so the
second context raises `RuntimeError` where the class binders raise an MRO
error. Three of the four fail at the scene; only the locking one lets both
transfers complete.

**Pickle.** `Context` refuses immediately, because the synthesized class exists
in no module. `InstanceContext` serializes without complaint and produces bytes
that cannot be loaded, which moves the failure out of the process that made the
mistake and into whatever later reads the cache or the queue.

A fifth option is not to lend roles to domain objects at all, which is what
`banking.services.money_transfer` does. It has none of these limitations and
gives up object identity in exchange.
"""

from __future__ import annotations

from banking.dci.base import BaseContext, context, playing
from banking.dci.class_binding import Context
from banking.dci.instance import InstanceContext
from banking.dci.serialized import SerializedContext
from banking.dci.transparent import RoleClass, TransparentContext

__all__ = [
    'BaseContext',
    'Context',
    'InstanceContext',
    'RoleClass',
    'SerializedContext',
    'TransparentContext',
    'context',
    'playing',
]
