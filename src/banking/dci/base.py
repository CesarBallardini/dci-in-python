"""The lifecycle every binder shares: the running context, and `BaseContext`.

A binder supplies `_bind`; everything around it -- entering, releasing, the
`ContextVar` lookup and the two guards -- lives here and is written once.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Any, ClassVar, Self, overload

if TYPE_CHECKING:
    from collections.abc import Callable

_current_context: contextvars.ContextVar[BaseContext] = contextvars.ContextVar('dci_context')


@overload
def context() -> BaseContext: ...


@overload
def context[RunningContext](expected: type[RunningContext]) -> RunningContext: ...


def context(expected: type | None = None) -> Any:
    """The context currently running, as seen from inside a role.

    A role never holds a reference to its peers; it asks the context for them.
    The value is held in a `ContextVar` rather than a module-level global so
    that the lookup remains correct under threads and under `async`.

    Passing the protocol a role requires -- `context(_RunningTransfer)` --
    types the result as that protocol, so a role reaches its peers without a
    `cast` at each point of use. The argument is deliberately not inspected:
    checking it would mean an `isinstance` against a protocol on every role
    call, and the context returned is whichever one `__enter__` installed
    either way. It states what the caller expects, for the type checker.

    Args:
        expected: the protocol or class the caller requires of the running
            context. Omit it to receive the context as a `BaseContext`.

    Returns:
        The context currently running.

    Raises:
        LookupError: if called outside any context.
    """
    return _current_context.get()


class BaseContext:
    """A use case reified: an object that exists while it runs.

    Subclasses declare which of their attributes play which role, and hold the
    participating data objects as ordinary attributes::

        class MoneyTransferContext(Context):
            roles = {'source': SourceAccount, 'destination': DestinationAccount}

    Entering binds every role; leaving unbinds them, including when the body
    raises -- `__exit__` never swallows the exception.

    Two guards live here, and both apply to all four contexts.

    **Binding is all-or-nothing.** A role that cannot be bound -- a slotted
    class, or an object already playing that part in another live context --
    aborts the whole `__enter__` and leaves nothing behind: participants bound
    so far are undone and the context variable is popped before the error
    surfaces. Without this, a context that failed part-way would remain
    installed as the current one for the rest of the thread's life, and the
    next role to call `context()` would receive an unrelated transfer.

    **A context is not re-entrant.** Entering an instance that is already
    running raises `RuntimeError` and says so. Without this guard the second
    entry would overwrite `_token`, and the outer exit would then reset a token
    that had already been spent.
    """

    roles: ClassVar[dict[str, type]] = {}

    #: Whether this instance is currently entered. A context represents a use
    #: case in progress, so entering the same one twice is a defect rather than
    #: a nesting feature. Reporting it here is clearer than the `Token ... has
    #: already been used once` that CPython would raise on the outer exit.
    _active: bool = False

    _token: contextvars.Token[BaseContext]

    #: What to run, in reverse, to put every participant back as it was. Each
    #: `_bind` appends its own undo, so a partial failure unwinds exactly what
    #: it managed to do and nothing else.
    _undo: list[Callable[[], None]]

    def __enter__(self) -> Self:
        """Bind each declared role to the object held in the matching attribute."""
        if self._active:
            raise RuntimeError(f'{type(self).__name__} is already running: a context is not re-entrant')
        self._token = _current_context.set(self)
        self._undo = []
        try:
            for attribute, role in self.roles.items():
                self._bind(getattr(self, attribute), role)
        except BaseException:
            self._release()
            raise
        self._active = True
        return self

    def __exit__(self, *exc_info: object) -> bool:
        """Restore every participant, then pop the context."""
        self._release()
        return False

    def _bind(self, obj: object, role: type) -> None:
        """Lend `role`'s behaviour to `obj`, and record how to remove it.

        Implemented by `Context`, `TransparentContext` and `InstanceContext`.
        An implementation must append its undo to `self._undo` as it goes, so
        that a failure part-way through leaves `_release` able to unwind
        exactly what succeeded.

        Raises:
            NotImplementedError: always -- `BaseContext` binds nothing itself.
        """
        raise NotImplementedError

    def _release(self) -> None:
        """Undo whatever `__enter__` completed, and always stand down.

        Every participant's undo is attempted even if an earlier one failed,
        and the context variable is popped in all cases. Allowing a failed undo
        to abort this would leave a finished context installed as the current
        one for the rest of the thread's life -- the same failure the
        all-or-nothing binding prevents, reached by a different route. It is
        reachable in practice: under `InstanceContext`, a method may already
        have been deleted by a second context that overlapped this one.

        The first failure is re-raised once everything has been restored, so
        the caller still learns about it.

        Raises:
            BaseException: whatever the first failing undo raised.
        """
        failure: BaseException | None = None
        try:
            for undo in reversed(self._undo):
                try:
                    undo()
                except BaseException as exc:  # noqa: BLE001 -- every undo runs; the first failure is kept
                    failure = failure or exc
        finally:
            self._undo = []
            self._active = False
            _current_context.reset(self._token)
        if failure is not None:
            raise failure
