"""`InstanceContext`: roles written into the instance rather than onto the class.

`test_limits.py` records where `Context` fails. This file records the trade
`InstanceContext` makes instead. Two of those failures do not occur here -- the
frozen dataclass and the synthesized class name -- and a third, the
declaratively mapped ORM entity, is covered in
`tests/integration/test_orm_roles.py`. In exchange, pickling fails later
instead of earlier, a role can no longer contribute a special method, and two
overlapping contexts corrupt each other silently.

Each test is paired against `MoneyTransferContext` where the contrast matters,
so the two mechanisms are compared by running them rather than by describing
them.
"""

from __future__ import annotations

import copy
import pickle
import threading
import time
import types
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import attrs
import pytest

from banking.contexts.money_transfer import InstanceMoneyTransferContext, MoneyTransferContext
from banking.data.account import Account, InsufficientFundsError
from banking.data.money import Money

if TYPE_CHECKING:
    from banking.roles.money_transfer import SourceAccount


class SlottedAccount:
    """No instance dictionary, so nothing to write a role into."""

    __slots__ = ('balance', 'holder')

    def __init__(self, holder: str, balance: Money) -> None:
        self.holder = holder
        self.balance = balance

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


@dataclass(frozen=True)
class FrozenAccount:
    """Refuses every `__setattr__` -- and `object.__setattr__` goes around it."""

    holder: str
    balance: Money

    def debit(self, amount: Money) -> None:
        object.__setattr__(self, 'balance', self.balance - amount)

    def credit(self, amount: Money) -> None:
        object.__setattr__(self, 'balance', self.balance + amount)


@attrs.define
class AttrsAccount:
    """`@define` means `slots=True`, so this one has no dictionary either."""

    holder: str
    balance: Money

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


# ---------------------------------------------------------------------------
# It is the same use case
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_it_moves_the_money(alice: Account, bob: Account) -> None:
    """Same participants, same script, same outcome as the class-bound version."""
    InstanceMoneyTransferContext(alice, bob, Money(250)).execute()

    assert (alice.balance, bob.balance) == (Money(750), Money(250))


@pytest.mark.unit
def test_it_refuses_a_transfer_beyond_the_balance(alice: Account, bob: Account) -> None:
    """The role's guard is the role's guard, whichever way it was lent out."""
    with pytest.raises(InsufficientFundsError):
        InstanceMoneyTransferContext(alice, bob, Money(5000)).execute()

    assert (alice.balance, bob.balance) == (Money(1000), Money(0))


@pytest.mark.unit
def test_the_roles_are_temporary(alice: Account, bob: Account) -> None:
    """Lent on the way in, taken back on the way out -- including the amount."""
    amount = Money(10)
    assert not hasattr(alice, 'transfer')

    with InstanceMoneyTransferContext(alice, bob, amount):
        assert hasattr(alice, 'transfer')
        assert hasattr(bob, 'receive')
        assert hasattr(amount, 'withdraw_from')

    assert not hasattr(alice, 'transfer')
    assert not hasattr(bob, 'receive')
    assert not hasattr(amount, 'withdraw_from')


@pytest.mark.unit
def test_roles_are_released_even_when_the_body_raises(alice: Account, bob: Account) -> None:
    """An exception inside the `with` still gives the participants back."""
    with pytest.raises(InsufficientFundsError):
        InstanceMoneyTransferContext(alice, bob, Money(5000)).execute()

    assert not hasattr(alice, 'transfer')


@pytest.mark.unit
def test_a_context_is_not_re_entrant(alice: Account, bob: Account) -> None:
    """The guard lives in the shared base, so both binders get it."""
    ctx = InstanceMoneyTransferContext(alice, bob, Money(10))

    with ctx, pytest.raises(RuntimeError, match='not re-entrant'):
        ctx.__enter__()


# ---------------------------------------------------------------------------
# What changes: two failures removed, and two behaviours that only differ
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_frozen_dataclass_can_play_a_role() -> None:
    """The limit that stops the idiomatic value object does not apply here.

    `Context` cannot bind here: a frozen dataclass rejects every `__setattr__`
    and `__class__` is an attribute like any other. Writing the method into the
    instance with `object.__setattr__` goes around the guard, which is right --
    a role is not domain state and the freeze was never about it.
    """
    source = FrozenAccount('Alice', Money(1000))
    destination = FrozenAccount('Bob', Money(0))

    with pytest.raises(Exception, match="cannot assign to field '__class__'"):
        MoneyTransferContext(source, destination, Money(250)).execute()

    InstanceMoneyTransferContext(source, destination, Money(250)).execute()

    assert (source.balance, destination.balance) == (Money(750), Money(250))


@pytest.mark.unit
def test_the_type_never_stops_being_the_real_one(alice: Account, bob: Account) -> None:
    """`type(obj)` remains the real class throughout.

    Under `Context` this reads `Account@SourceAccount`, a class that exists in
    no file. Here `type(alice)` is `Account` throughout, and the method is a
    perfectly ordinary bound method whose `__qualname__` names the role it came
    from, so a traceback refers to a file that exists.
    """
    with MoneyTransferContext(alice, bob, Money(10)):
        assert type(alice).__name__ == 'Account@SourceAccount'

    with InstanceMoneyTransferContext(alice, bob, Money(10)):
        assert type(alice) is Account
        # Inside the context `alice` is playing `SourceAccount`; saying so is
        # what makes `transfer` visible to a checker. Note the cast is to the
        # *role*, not to the synthesized class -- there is no synthesized class
        # here, which is the property this test exists to pin down.
        transfer = cast('SourceAccount', alice).transfer
        assert isinstance(transfer, types.MethodType)
        assert transfer.__qualname__ == 'SourceAccount.transfer'


@pytest.mark.unit
def test_neither_binder_survives_pickling_but_they_fail_differently(alice: Account, bob: Account) -> None:
    """Both refuse the round trip, and the instance-bound one refuses *late*.

    `Context` fails immediately: the object's class is
    `Account@SourceAccount`, pickle cannot find that in any module because it
    is in no module, and `dumps` raises on the spot.

    `InstanceContext` is worse. `dumps` **succeeds** -- a bound method pickles
    as "call `getattr` on this object with this name" -- and produces bytes
    that cannot be loaded, because at load time the reconstructed account has
    no `transfer` for `getattr` to find. So the failure moves: out of the
    process that made the mistake, into whatever later reads the cache, the
    queue or the session, with a traceback that says nothing about roles.

    Serializing a domain object mid-use-case is a mistake either way. Only one
    of the two reports it while it can still be acted on.
    """
    with MoneyTransferContext(alice, bob, Money(10)), pytest.raises(pickle.PicklingError):
        pickle.dumps(alice)

    blob = b''
    with InstanceMoneyTransferContext(alice, bob, Money(10)):
        blob = pickle.dumps(alice)  # no complaint here...

    with pytest.raises(AttributeError, match='transfer'):
        pickle.loads(blob)  # noqa: S301 -- our own bytes, this test's own process


@pytest.mark.unit
def test_deepcopy_survives_either_binder(alice: Account, bob: Account) -> None:
    """`copy.deepcopy` does not need to name the class, so it goes through."""
    with MoneyTransferContext(alice, bob, Money(10)):
        assert copy.deepcopy(alice).balance == Money(1000)

    with InstanceMoneyTransferContext(alice, bob, Money(10)):
        assert copy.deepcopy(alice).balance == Money(1000)


# ---------------------------------------------------------------------------
# What does not change: the same limit, for a different reason
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_slots_still_refuse_a_role() -> None:
    """Same refusal as `Context`, different error: there is no dictionary.

    `Context` fails at `__class__` assignment with `object layout differs`.
    This one gets as far as trying to store the method and finds nowhere to put
    it. Neither mechanism can lend a role to a slotted object.
    """
    ctx = InstanceMoneyTransferContext(
        SlottedAccount('Alice', Money(1000)),
        SlottedAccount('Bob', Money(0)),
        Money(250),
    )

    with pytest.raises(AttributeError, match='transfer'):
        ctx.execute()


@pytest.mark.unit
def test_an_attrs_class_still_refuses_a_role() -> None:
    """`@attrs.define` is slotted by default, so it lands in the same place."""
    ctx = InstanceMoneyTransferContext(
        AttrsAccount('Alice', Money(1000)),
        AttrsAccount('Bob', Money(0)),
        Money(250),
    )

    with pytest.raises(AttributeError):
        ctx.execute()


@pytest.mark.unit
def test_a_failed_binding_leaves_nothing_behind() -> None:
    """All-or-nothing holds here too, and it has more to undo than `Context` does.

    The amount binds first or the destination does, depending on dictionary
    order; whichever got its methods must lose them again when the slotted
    source refuses. And the context must not stay installed.
    """
    amount = Money(250)
    destination = Account('Bob', Money(0))

    with pytest.raises(AttributeError):
        InstanceMoneyTransferContext(SlottedAccount('Alice', Money(1000)), destination, amount).execute()

    assert not hasattr(amount, 'withdraw_from')
    assert not hasattr(destination, 'receive')

    from banking.dci import context  # noqa: PLC0415 -- imported here to read the state this test is about

    with pytest.raises(LookupError):
        context()


# ---------------------------------------------------------------------------
# What it costs: two problems `Context` does not have
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_role_cannot_contribute_a_dunder() -> None:
    """Special methods are resolved on the type, never on the instance.

    A role that wants to make its player comparable, iterable or callable can
    do it under `Context` -- the synthesized class is a real class -- and
    cannot do it here at all. The method lands in the dictionary and the
    operator walks straight past it.
    """

    class ComparableRole:
        def __lt__(self, other: object) -> bool:
            return True

    amount = Money(5)
    object.__setattr__(amount, '__lt__', types.MethodType(ComparableRole.__lt__, amount))

    # Called by name it is there and it answers.
    assert amount.__lt__(Money(1)) is True
    # Used as an operator it may as well not exist: `Money.__lt__` wins, and
    # `Money(5) < Money(1)` is False.
    assert (amount < Money(1)) is False


@pytest.mark.unit
def test_two_live_contexts_are_refused_at_the_scene() -> None:
    """The second context is turned away where `Context` raises its MRO error.

    Both refuse at bind time, and neither is a way to run two contexts over one
    object -- that is `SerializedContext`. What the refusal buys is that the
    failure belongs to the context that caused it: the first context keeps its
    roles, finishes normally, and nothing it is holding is removed underneath
    it.
    """
    shared = Account('Erin', Money(1_000_000))
    first = InstanceMoneyTransferContext(shared, Account('Frank', Money(0)), Money(10))
    second = InstanceMoneyTransferContext(shared, Account('Grace', Money(0)), Money(20))

    first.__enter__()

    with pytest.raises(RuntimeError, match='already has'):
        second.__enter__()

    # The refused context left nothing behind, and the first one is untouched.
    assert hasattr(shared, 'transfer')
    first.__exit__()
    assert not hasattr(shared, 'transfer')


@pytest.mark.unit
def test_binding_will_not_clobber_an_attribute_the_object_owns() -> None:
    """The same check, reached without a second context.

    A domain object that happens to carry a name a role also defines is not
    overwritten, which matters because `_strip` deletes on the way out: without
    the check the object would lose its own attribute permanently.
    """

    class AccountWithNotes(Account):
        def __init__(self, holder: str, balance: Money) -> None:
            super().__init__(holder, balance)
            self.transfer = 'last transfer: 2026-08-01'  # its own state, not a role

    source = AccountWithNotes('Erin', Money(1_000))

    with pytest.raises(RuntimeError, match='already has'):
        InstanceMoneyTransferContext(source, Account('Frank', Money(0)), Money(10)).execute()

    assert source.transfer == 'last transfer: 2026-08-01'


@pytest.mark.unit
def test_the_collision_is_refused_with_real_threads() -> None:
    """Same refusal, served by two concurrent requests.

    Compare `test_the_collision_happens_with_real_threads` in `test_limits.py`,
    where the fast thread dies of a `TypeError` at bind time. The shape is now
    the same: the thread that arrives second is the one that fails, and the
    slow thread -- the request that had done nothing wrong -- completes.
    """
    shared = Account('Erin', Money(1_000_000))
    failures: list[tuple[str, str]] = []
    role_bound = threading.Event()

    def slow_thread() -> None:
        try:
            ctx = InstanceMoneyTransferContext(shared, Account('Frank', Money(0)), Money(5))
            with ctx:
                role_bound.set()
                time.sleep(0.3)  # the other thread binds and unbinds inside this gap
                ctx.run_script()
        except (AttributeError, TypeError, RuntimeError) as exc:
            failures.append(('slow', type(exc).__name__))

    def fast_thread() -> None:
        role_bound.wait(2)
        try:
            InstanceMoneyTransferContext(shared, Account('Grace', Money(0)), Money(7)).execute()
        except (AttributeError, TypeError, RuntimeError) as exc:
            failures.append(('fast', type(exc).__name__))

    threads = [threading.Thread(target=slow_thread), threading.Thread(target=fast_thread)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    # The thread that arrived second is the one that fails, and it says why.
    assert ('fast', 'RuntimeError') in failures
    assert not [failure for failure in failures if failure[0] == 'slow']
