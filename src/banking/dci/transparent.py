"""`Context`, with the synthesized class wearing the data class's name."""

from __future__ import annotations

import functools

from banking.dci.class_binding import Context


class RoleClass(type):
    """Metaclass of a synthesized class that reports the data class's name.

    The renaming is what changes the error messages: `__name__` feeds CPython's
    `tp_name`, which is where `AttributeError` and `TypeError` take the name
    they print. A metaclass cannot reach that. Defining `__name__` as a property
    on the metaclass intercepts attribute access but leaves the C-level name
    unchanged, so error messages continue to report `Account@SourceAccount`.

    The metaclass covers the other half: keeping the substitution inspectable.
    `repr()` reports both classes at once, and `__dci_data__` / `__dci_role__`
    expose them individually. The intent is that the class remains open to
    inspection, not that the role is concealed.

    The class is public for the same reason. Those two attributes are the
    supported way to ask a renamed class what it is built from, and a caller
    cannot express that question to a type checker -- `cast('RoleClass',
    type(obj))` -- without a name to refer to.
    """

    __dci_data__: type
    __dci_role__: type

    def __repr__(cls) -> str:
        """`<class 'banking.data.account.Account' playing 'SourceAccount'>`."""
        return f"<class '{cls.__module__}.{cls.__qualname__}' playing '{cls.__dci_role__.__name__}'>"


@functools.cache
def _disguised_class_with_role(cls: type, role: type) -> type:
    """As `_class_with_role`, but the result reports `cls`'s name.

    Same MRO, same `isinstance`, same runtime behaviour. Only the labels
    change, and they change to those of a class that exists in a source file.
    """
    synthesized = RoleClass(
        f'{cls.__name__}@{role.__name__}',
        (role, cls),
        {'__dci_data__': cls, '__dci_role__': role},
    )
    synthesized.__name__ = cls.__name__
    synthesized.__qualname__ = cls.__qualname__
    synthesized.__module__ = cls.__module__
    return synthesized


class TransparentContext(Context):
    """`Context`, with the synthesized class carrying the data class's name.

    Everything `Context` does, plus one addition: the class built at bind time
    reports itself as `Account` rather than `Account@SourceAccount` -- in
    `type(obj).__name__`, in `repr(type(obj))`, and in the `AttributeError` and
    `TypeError` messages CPython builds from the type's name. Tracebacks stop
    naming a class that cannot be opened.

    The binding itself is unchanged: same MRO, same `isinstance`, same `id()`,
    same failures on `__slots__` and frozen dataclasses, same MRO collision
    when two contexts overlap. This is a labelling decision only.

    The trade-off is worth stating in both directions. Against: an object whose
    type prints as `Account` carries a `transfer` method that `Account` does
    not define, so searching the source for it finds nothing. In favour: the
    previous name referred to a class that exists in no file, which is not more
    helpful. The compromise is that the underlying classes remain available on
    the class itself::

        type(obj).__dci_role__   # <class 'SourceAccount'>
        type(obj).__dci_data__   # <class 'Account'>
        repr(type(obj))          # <class 'banking...Account' playing 'SourceAccount'>

    A type checker cannot see those two attributes on its own, since
    `type(obj)` is statically `type[Account]`, so the form that passes
    `make types` names the metaclass they are declared on::

        cast('RoleClass', type(obj)).__dci_role__

    `pickle` still refuses, with a more useful message: it reports that the
    class is *not the same object as* the `Account` it can import, rather than
    that it cannot find `Account@SourceAccount` at all.
    """

    def _bind(self, obj: object, role: type) -> None:
        """Install a class that mixes `role` over `obj`'s class, keeping its name."""
        original = obj.__class__
        obj.__class__ = _disguised_class_with_role(original, role)
        self._undo.append(functools.partial(self._restore, obj, original))
