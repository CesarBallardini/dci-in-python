"""Where class binding fails. These tests assert the failures deliberately.

`obj.__class__ = ...` provides correct DCI semantics at a cost. Asserting
each cost as a test means that a future Python release which removes one of
them fails the suite, rather than leaving the documentation quietly wrong.
"""

from __future__ import annotations

import contextvars
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import attrs
import pytest

from banking.contexts.money_transfer import MoneyTransferContext
from banking.data.account import Account
from banking.data.money import Money
from banking.dci import context

if TYPE_CHECKING:
    from collections.abc import Callable


def in_a_fresh_context[Result](work: Callable[[], Result]) -> Result:
    """Run `work` with a `ContextVar` state of its own, and return what it returns.

    Three of the tests below leave a finished context installed, which is part
    of what they measure. `contextvars.copy_context()` gives the scenario its
    own copy of that state, so the leftover cannot reach the tests that follow.
    """
    return contextvars.copy_context().run(work)


class SlottedAccount:
    """An `Account` optimized for memory -- and therefore ineligible for a role."""

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
    """The idiomatic spelling of an immutable entity -- and it cannot play a role.

    Functional updates through `object.__setattr__`, the usual escape hatch, so
    it is a genuine working account and not a straw man: it satisfies
    `AccountLike` in full. The refusal has nothing to do with the protocol.
    """

    holder: str
    balance: Money

    def debit(self, amount: Money) -> None:
        object.__setattr__(self, 'balance', self.balance - amount)

    def credit(self, amount: Money) -> None:
        object.__setattr__(self, 'balance', self.balance + amount)


@pytest.mark.unit
def test_slots_make_role_binding_illegal() -> None:
    """Python only reassigns `__class__` between identical object layouts.

    Adding a `__dict__` to a slotted class changes the layout. There is no way
    around it, and plenty of library-generated classes use slots.
    """
    ctx = MoneyTransferContext(
        SlottedAccount('Alice', Money(100)),
        SlottedAccount('Bob', Money(0)),
        Money(10),
    )

    with pytest.raises(TypeError, match='object layout differs'):
        ctx.execute()


@pytest.mark.unit
def test_a_frozen_dataclass_cannot_play_a_role(alice: Account, bob: Account) -> None:
    """The same outcome as `__slots__`, reached by the idiomatic spelling.

    A frozen dataclass overrides `__setattr__` to reject every assignment,
    and `__class__` is an attribute like any other. The standard way to write
    `Money`, and any other value object, is therefore the one form that
    cannot take the `TransferAmount` part.
    """
    ctx = MoneyTransferContext(FrozenAccount('Alice', Money(1000)), FrozenAccount('Bob', Money(0)), Money(250))

    # The error names the field it refuses to assign, and that field is
    # `__class__` itself: the freeze applies to role binding as well.
    with pytest.raises(Exception, match="cannot assign to field '__class__'"):
        ctx.execute()


@pytest.mark.unit
def test_an_attrs_class_cannot_play_a_role() -> None:
    """The other common way of writing a domain object reaches the same limit.

    `@attrs.define` sets `slots=True` by default; that is the documented and
    recommended form, not an optimization selected deliberately. Between this,
    frozen dataclasses and SQLAlchemy's declarative base, the ways of writing
    an entity that rule out class binding outnumber the ways that allow it.
    """

    @attrs.define
    class AttrsAccount:
        holder: str
        balance: Money

        def debit(self, amount: Money) -> None:
            self.balance = self.balance - amount

        def credit(self, amount: Money) -> None:
            self.balance = self.balance + amount

    source = AttrsAccount('Alice', Money(1000))
    destination = AttrsAccount('Bob', Money(0))

    with pytest.raises(TypeError, match='object layout differs'):
        MoneyTransferContext(source, destination, Money(250)).execute()


@pytest.mark.unit
def test_two_live_contexts_over_one_account_collide() -> None:
    """`__class__` is global state of the *object*; DCI uses it as context-local.

    The second context tries to stack `SourceAccount` on top of a class that
    already has it, and there is no consistent MRO for that. This is not an
    exotic case -- this is a server with two requests touching one account.
    """
    shared = Account('Erin', Money(1_000_000))
    first = MoneyTransferContext(shared, Account('Frank', Money(0)), Money(10))
    second = MoneyTransferContext(shared, Account('Grace', Money(0)), Money(20))

    first.__enter__()
    try:
        assert type(shared).__name__ == 'Account@SourceAccount'

        # `\s+`, not a space: CPython line-wrapped this message between
        # "resolution" and "order" until 3.13 unwrapped it, so the wording is
        # not something to depend on more tightly than necessary.
        with pytest.raises(TypeError, match=r'[Cc]onsistent method resolution\s+order'):
            second.__enter__()
    finally:
        first.__exit__()

    assert type(shared).__name__ == 'Account'


@pytest.mark.unit
def test_two_live_contexts_wanting_different_roles_bind_without_complaint() -> None:
    """The MRO error only fires when the second context wants the *same* role.

    An account paying one transfer out while a second transfer pays into it is
    an ordinary pair of requests, and `DestinationAccount` over
    `Account@SourceAccount` has a consistent MRO. Nothing refuses, so the
    collision above is not a guard against two live contexts over one object:
    it is what happens when one role is stacked on itself.

    Unwound in the order a nested pair of `with` blocks would unwind, the stack
    still comes apart cleanly. That order is the only thing holding it
    together, and the next test is what happens without it.
    """
    shared = Account('Erin', Money(1000))
    paying_out = MoneyTransferContext(shared, Account('Frank', Money(0)), Money(10))
    paid_into = MoneyTransferContext(Account('Grace', Money(500)), shared, Money(20))

    def scenario() -> list[str]:
        paying_out.__enter__()
        paid_into.__enter__()
        stacked = [cls.__name__ for cls in type(shared).__mro__]
        paid_into.__exit__()
        paying_out.__exit__()
        return stacked

    assert in_a_fresh_context(scenario) == [
        'Account@SourceAccount@DestinationAccount',
        'DestinationAccount',
        'Account@SourceAccount',
        'SourceAccount',
        'Account',
        'object',
    ]
    assert type(shared) is Account


@pytest.mark.unit
def test_overlapping_exits_leave_the_role_bound_for_good() -> None:
    """Each context restores the class it found, which is correct only while they nest.

    Two requests that overlap without nesting -- the one that opened first is
    also the one that closes first -- make the second put back a class that
    already carries the first one's role. Nothing raises anywhere along the
    way. The account comes out of the pair of transfers still playing
    `SourceAccount`, with no context running and nothing to take the role back.
    """
    shared = Account('Erin', Money(1000))
    paying_out = MoneyTransferContext(shared, Account('Frank', Money(0)), Money(10))
    paid_into = MoneyTransferContext(Account('Grace', Money(500)), shared, Money(20))

    def scenario() -> None:
        paying_out.__enter__()
        paid_into.__enter__()
        paying_out.__exit__()  # the transfer that opened first also closes first
        paid_into.__exit__()

    in_a_fresh_context(scenario)

    assert type(shared).__name__ == 'Account@SourceAccount'
    assert hasattr(shared, 'transfer')
    # And it passes every check anyone would think to write about it.
    assert isinstance(shared, Account)


@pytest.mark.unit
def test_the_left_over_role_breaks_the_next_transfer_out_of_that_account() -> None:
    """This is what makes the leak permanent rather than cosmetic.

    The account is now an `Account@SourceAccount` outside every context, so the
    next context that asks it to play `SourceAccount` stacks the role on itself
    and gets the MRO error of the first test. The request that fails is one
    that did nothing wrong, arbitrarily later, and the two transfers that
    caused it have long since returned successfully.
    """
    shared = Account('Erin', Money(1000))
    paying_out = MoneyTransferContext(shared, Account('Frank', Money(0)), Money(10))
    paid_into = MoneyTransferContext(Account('Grace', Money(500)), shared, Money(20))

    def scenario() -> None:
        paying_out.__enter__()
        paid_into.__enter__()
        paying_out.__exit__()
        paid_into.__exit__()

    in_a_fresh_context(scenario)

    with pytest.raises(TypeError, match=r'[Cc]onsistent method resolution\s+order'):
        MoneyTransferContext(shared, Account('Heidi', Money(0)), Money(1)).execute()


@pytest.mark.unit
def test_the_first_context_to_leave_strips_the_role_from_the_one_still_inside() -> None:
    """The other half of the overlap, and it lands on a transfer in flight.

    The leak is what is left afterwards; this is what happens during. When the
    first context restores the account's original class, the second context is
    still running and loses `DestinationAccount` from under it, so the transfer
    that was mid-script fails on a missing `receive` with nothing in the
    message about roles, contexts or the other request.

    Two threads rather than one call after another, because each thread has its
    own `ContextVar` state: in a single thread the second context's roles are
    reached through a variable the first exit already popped, and the failure
    arrives as a `LookupError` before it can get as far as the missing method.
    Two requests is the shape this takes in a server, and it is the shape that
    reaches the account.
    """
    shared = Account('Erin', Money(1000))
    paying_out_inside = threading.Event()
    paid_into_inside = threading.Event()
    paying_out_left = threading.Event()
    failures: list[str] = []

    def paying_out() -> None:
        held = MoneyTransferContext(shared, Account('Frank', Money(0)), Money(5))
        with held:
            paying_out_inside.set()
            paid_into_inside.wait(2)
            held.run_script()
        paying_out_left.set()

    def paid_into() -> None:
        paying_out_inside.wait(2)
        held = MoneyTransferContext(Account('Grace', Money(1000)), shared, Money(7))
        try:
            with held:
                paid_into_inside.set()
                paying_out_left.wait(2)  # the other transfer leaves inside this gap
                held.run_script()
        except AttributeError as exc:
            failures.append(str(exc))

    threads = [threading.Thread(target=paying_out), threading.Thread(target=paid_into)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert failures == ["'Account' object has no attribute 'receive'"]
    # And the leak is still there underneath, so the account carries both
    # consequences of one overlap.
    assert type(shared).__name__ == 'Account@SourceAccount'


@pytest.mark.unit
def test_the_overlapping_exit_also_leaves_a_finished_context_installed() -> None:
    """The class is not the only state put back wrong; the `ContextVar` is too.

    A `Token` restores the value it replaced, and the value the second context
    replaced was the first context. Resetting the two out of order therefore
    reinstalls a context that has already finished, and a role called
    afterwards -- through the class the previous test left behind -- reaches
    `context()` and is handed it: participants that no longer hold their roles,
    and an amount that is a plain `Money` again.

    Both guards in `BaseContext` are working correctly here. Neither one is
    about this: they cover a context that fails part-way and a context entered
    twice, and this is two contexts that each succeeded.
    """
    shared = Account('Erin', Money(1000))
    paying_out = MoneyTransferContext(shared, Account('Frank', Money(0)), Money(10))
    paid_into = MoneyTransferContext(Account('Grace', Money(500)), shared, Money(20))

    def scenario() -> bool:
        paying_out.__enter__()
        paid_into.__enter__()
        paying_out.__exit__()
        paid_into.__exit__()
        return context() is paying_out

    assert in_a_fresh_context(scenario)


@pytest.mark.unit
def test_the_collision_happens_with_real_threads() -> None:
    """The same failure, served by two concurrent requests.

    The slow thread holds the role while the fast one tries to take it, and the
    fast one dies with an MRO error that has nothing to do with moving money.
    Worse is the timing this test does *not* provoke: had the slow thread left
    its context first, the fast one would have kept running with its role
    silently stripped -- a wrong answer instead of an exception, in the code
    that moves the money.
    """
    shared = Account('Erin', Money(1_000_000))
    failures: list[tuple[str, str]] = []
    moved: list[Money] = []
    role_bound = threading.Event()

    def slow_thread() -> None:
        try:
            destination = Account('Frank', Money(0))
            ctx = MoneyTransferContext(shared, destination, Money(5))
            with ctx:
                role_bound.set()
                time.sleep(0.3)  # the other thread opens ITS context in this gap
                ctx.run_script()
            moved.append(destination.balance)
        except (TypeError, RuntimeError) as exc:
            failures.append(('slow', type(exc).__name__))

    def fast_thread() -> None:
        role_bound.wait(2)
        try:
            MoneyTransferContext(shared, Account('Grace', Money(0)), Money(7)).execute()
        except (TypeError, RuntimeError) as exc:
            failures.append(('fast', type(exc).__name__))

    threads = [threading.Thread(target=slow_thread), threading.Thread(target=fast_thread)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    # The slow request went through and the fast one died of an MRO error that
    # has nothing to do with moving money.
    assert moved == [Money(5)]
    assert ('fast', 'TypeError') in failures


@pytest.mark.unit
def test_the_synthesized_class_exists_in_no_source_file(alice: Account, bob: Account) -> None:
    """The reported class cannot be opened, searched for, or auto-completed."""
    with MoneyTransferContext(alice, bob, Money(10)):
        synthesized = type(alice)

        assert synthesized.__name__ == 'Account@SourceAccount'
        # And it claims to live in the module that called `type()` -- the DCI
        # machinery, which knows nothing about accounts and where no such class
        # is written. A traceback will point everyone at the wrong file.
        assert synthesized.__module__ == 'banking.dci.class_binding'
        assert synthesized.__module__ != Account.__module__
