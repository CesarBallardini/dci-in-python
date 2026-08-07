"""The role as a wrapper: DCI's structure without role binding, and what that costs.

The wrapper works where class binding fails, because nothing reassigns
`__class__`. It is also not the account it wraps, which is the property role
binding exists to keep.
"""

from __future__ import annotations

import pytest

from banking.alternatives import SourceWrapper, WrappedTransfer
from banking.data.account import Account
from banking.data.money import Money


@pytest.mark.unit
def test_the_wrapper_transfers(alice: Account, bob: Account) -> None:
    WrappedTransfer(alice, bob, Money(50)).execute()

    assert (alice.balance, bob.balance) == (Money(950), Money(50))


@pytest.mark.unit
def test_the_wrapper_survives_slots() -> None:
    """No `__class__` reassignment, so the thing DCI cannot do costs nothing here."""

    class SlottedAccount:
        __slots__ = ('balance', 'holder')

        def __init__(self, holder: str, balance: Money) -> None:
            self.holder, self.balance = holder, balance

        def debit(self, amount: Money) -> None:
            self.balance = self.balance - amount

        def credit(self, amount: Money) -> None:
            self.balance = self.balance + amount

    source = SlottedAccount('Alice', Money(500))
    destination = SlottedAccount('Bob', Money(0))

    WrappedTransfer(source, destination, Money(50)).execute()

    assert (source.balance, destination.balance) == (Money(450), Money(50))


@pytest.mark.unit
def test_the_wrapper_is_not_the_account(alice: Account) -> None:
    """And this is what it cost: the object playing the role is a different object."""
    wrapper = SourceWrapper(alice, WrappedTransfer(alice, alice, Money(0)))

    assert wrapper is not alice
    assert not isinstance(wrapper, Account)
    assert wrapper.balance == alice.balance  # delegation works; identity does not
