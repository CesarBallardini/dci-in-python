"""`Context`, with every participant locked for the duration of the use case."""

from __future__ import annotations

import threading
import weakref
from typing import Self

from banking.dci.class_binding import Context

_lock_registry: dict[int, threading.RLock] = {}
_lock_registry_guard = threading.Lock()


def _lock_for(obj: object) -> threading.RLock:
    """The lock representing `obj`, created on first use.

    Keyed by `id()` rather than by the object itself, which matters: `Money` is
    a value object, so two equal amounts hash and compare equal, and a
    dictionary keyed by value would give two distinct participants the same
    lock. Roles are lent to objects, so identity is the correct key. A
    finalizer removes the entry when the object is collected, which prevents
    the registry from growing without bound in a long-running process.
    """
    key = id(obj)
    with _lock_registry_guard:
        lock = _lock_registry.get(key)
        if lock is None:
            lock = _lock_registry[key] = threading.RLock()
            weakref.finalize(obj, _lock_registry.pop, key, None)
        return lock


class SerializedContext(Context):
    """`Context`, with the participants locked for the duration of the use case.

    If two contexts cannot share an object's `__class__`, they must not hold it
    at the same time. Entering acquires one lock per participant and leaving
    releases them, so a second context over the same account waits rather than
    finding the class already replaced.

    Two properties are worth stating explicitly.

    **Locks are acquired in a fixed order**, sorted by `id()`. Without this,
    two transfers running in opposite directions between the same two accounts
    would each hold what the other needs, which is a deadlock and a worse
    defect than the one being fixed. A fixed order makes it impossible.

    **The lock is not a cost DCI introduces.** Role binding is not the only
    thing two concurrent transfers do to one account: `balance = balance -
    amount` is a read, a subtraction and a write, and two threads interleaving
    there lose an update whether or not roles are involved. Any code moving
    money between shared mutable objects needs this lock already, and with a
    database behind it, the corresponding row lock. What role binding adds is
    that the same race surfaces as a `TypeError` instead of a silent lost
    update.

    What this does **not** do is allow two contexts to play one object at the
    same time. It serializes them, so throughput on a contended account is one
    use case at a time -- the same behaviour a `SELECT ... FOR UPDATE` gives.
    Participants that share nothing never interact and run fully in parallel.

    Nothing here applies across processes, and nothing needs to: separate
    processes have separate objects. `tests/unit/test_serialized_roles.py`
    measures each of these properties.
    """

    _locks: list[threading.RLock]

    def __enter__(self) -> Self:
        """Take every participant's lock in a fixed order, then bind."""
        # Sorting by identity is what rules out the opposite-direction
        # deadlock. See the class docstring.
        self._locks = [_lock_for(obj) for obj in sorted((getattr(self, a) for a in self.roles), key=id)]
        for lock in self._locks:
            lock.acquire()
        try:
            return super().__enter__()
        except BaseException:
            self._unlock()
            raise

    def __exit__(self, *exc_info: object) -> bool:
        """Unbind, then release the locks regardless of outcome."""
        try:
            return super().__exit__(*exc_info)
        finally:
            self._unlock()

    def _unlock(self) -> None:
        """Release the locks in reverse order and discard them."""
        for lock in reversed(self._locks):
            lock.release()
        self._locks = []
