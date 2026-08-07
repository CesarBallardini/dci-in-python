"""The binder that never touches the class: role methods on the instance."""

from __future__ import annotations

import functools
import types

from banking.dci.base import BaseContext


def _role_methods(role: type) -> list[str]:
    """The names a role lends to whatever plays it.

    Only what the role defines itself, and only ordinary methods. Two kinds of
    attribute are excluded deliberately. Dunders, because special methods are
    resolved on the type, so one placed in an instance's `__dict__` would never
    run -- see `InstanceContext`. And anything not directly callable,
    `property` included, because a descriptor has to live on a class to have
    any effect.

    Roles do not inherit from one another in DCI, so `vars()` is sufficient and
    there is no MRO to walk.
    """
    return [name for name, value in vars(role).items() if callable(value) and not name.startswith('__')]


class InstanceContext(BaseContext):
    """Roles bound by writing the role's methods into the object's `__dict__`.

    The same DCI semantics without synthesizing a class: each of the role's
    methods is written into the instance as a bound method and removed again on
    the way through `__exit__`. `object.__setattr__` is used rather than plain
    assignment so that a domain object with an opinion about attribute setting
    -- a frozen dataclass, most obviously -- cannot refuse. This is deliberate:
    the role is not domain state, and the binding lasts exactly as long as the
    context.

    What it gains over `Context`, all measured in
    `tests/unit/test_instance_roles.py`: frozen dataclasses and declaratively
    mapped ORM entities can play roles, and `type(obj)` remains the real class,
    so tracebacks and debuggers report something that exists.

    What it costs, and why it is not the default:

    * **`__slots__` and `attrs` still refuse**, because there is no instance
      dictionary to write into. Same limitation, different error.
    * **A role cannot contribute a special method.** Dunders are resolved on
      the type, never on the instance, so one written into `__dict__` would
      never run. `_role_methods` therefore declines to bind them at all. Under
      `Context` the same role method works normally.
    * **Pickling fails late rather than early.** `Context` refuses at `dumps`.
      Here `dumps` succeeds -- a bound method pickles as "call `getattr` on
      this object with this name" -- and produces bytes that cannot be loaded,
      because the reconstructed object has no such attribute. The failure moves
      out of the process that made the mistake.
    * **Two live contexts are refused rather than serialized.** `_bind` will not
      write over a name the object already has, so the second context raises
      `RuntimeError` where `Context` raises an MRO error -- both at the scene,
      neither of them a way to run two contexts at once. Only
      `SerializedContext` does that. The check is what keeps `_strip` honest as
      well: a context can only ever remove the names it installed itself, so no
      exit takes a method another context is still using.

    The refusal is a check, not a lock. Two threads entering at the same
    instant can both find the name absent and both write; the window is narrow
    but real, and closing it is what `SerializedContext` is for.
    """

    def _bind(self, obj: object, role: type) -> None:
        """Write `role`'s methods into `obj`'s dictionary as bound methods.

        Raises:
            RuntimeError: if `obj` already has an attribute of that name.
        """
        bound: list[str] = []
        # Registered before the first assignment and extended as each one
        # succeeds, so a failure part-way through a role unwinds that role too.
        self._undo.append(functools.partial(self._strip, obj, bound))
        # `getattr` rather than `vars()`: an object with no `__dict__` has to
        # reach `object.__setattr__` below and fail there, as it always has.
        instance_dict: dict[str, object] = getattr(obj, '__dict__', {})
        for name in _role_methods(role):
            if name in instance_dict:
                raise RuntimeError(
                    f'{type(obj).__name__} already has {name!r}: instance binding will not overwrite it. '
                    f'Another context is playing this role, or the object defines that name itself.'
                )
            object.__setattr__(obj, name, types.MethodType(getattr(role, name), obj))
            bound.append(name)

    @staticmethod
    def _strip(obj: object, names: list[str]) -> None:
        """Remove the lent methods from `obj`."""
        for name in names:
            object.__delattr__(obj, name)
