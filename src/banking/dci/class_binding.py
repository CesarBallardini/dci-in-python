"""The default binder: the role mixed into the object's class at runtime."""

from __future__ import annotations

import functools

from banking.dci.base import BaseContext


@functools.cache
def _class_with_role(cls: type, role: type) -> type:
    """Build, once, the class that mixes `role` over `cls`.

    The role comes first in the bases so that its methods take precedence over
    the data class's. Caching prevents a busy context from synthesizing a fresh
    class on every call; it is unbounded deliberately, since the set of
    (class, role) pairs in a program is fixed and small.
    """
    return type(f'{cls.__name__}@{role.__name__}', (role, cls), {})


class Context(BaseContext):
    """Roles bound by reassigning the object's class. The default.

    Entering installs a synthesized subclass that mixes the role over the
    object's own class; leaving restores the original. The object keeps its
    `id()` and remains an instance of its original class for `isinstance`.

    The limitations are asserted in `tests/unit/test_limits.py` rather than
    only described here:

    * binding is illegal on classes with `__slots__`, because the object layout
      differs, and on frozen dataclasses, because `__class__` is an attribute
      like any other and the generated `__setattr__` refuses all of them;
    * two live contexts over the same object produce an unsolvable MRO when they
      want the same role, because `__class__` is state of the *object* while DCI
      uses it as though it were state of the *context*;
    * two live contexts wanting *different* roles of the same object bind
      without complaint, and each restores the class it found on the way in. Two
      that overlap without nesting therefore leave the object playing the first
      one's role permanently, and nothing raises to say so;
    * the synthesized class exists in no source file, so a traceback names a
      class that cannot be opened, and no type checker can be shown it.
    """

    def _bind(self, obj: object, role: type) -> None:
        """Install a class that mixes `role` over `obj`'s current class."""
        original = obj.__class__
        obj.__class__ = _class_with_role(original, role)
        # Recorded only after the reassignment succeeds, so the undo never
        # touches an object this context did not change.
        self._undo.append(functools.partial(self._restore, obj, original))

    @staticmethod
    def _restore(obj: object, original: type) -> None:
        """Restore `obj`'s original class."""
        obj.__class__ = original
