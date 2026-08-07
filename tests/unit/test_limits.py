"""Where class binding fails. These tests assert the failures deliberately.

`obj.__class__ = ...` provides correct DCI semantics at a cost. Asserting
each cost as a test means that a future Python release which removes one of
them fails the suite, rather than leaving the documentation quietly wrong.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import attrs
import pytest

from banking.contexts.money_transfer import MoneyTransferContext
from banking.data.account import Account
from banking.data.money import Money


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
