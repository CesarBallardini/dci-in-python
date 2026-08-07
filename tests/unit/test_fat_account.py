"""Design 1: the account that knows too much. It moves the money, and that was never in question.

What this records is where the transfer ended up: on the entity, which will go
on to learn about fees, daily limits and posting hours.
"""

from __future__ import annotations

import pytest

from banking.alternatives import FatAccount
from banking.data.account import InsufficientFundsError
from banking.data.money import Money


@pytest.mark.unit
def test_the_fat_account_transfers() -> None:
    source, destination = FatAccount('Alice', Money(1000)), FatAccount('Bob', Money(0))

    source.transfer_to(destination, Money(250))

    assert (source.balance, destination.balance) == (Money(750), Money(250))


@pytest.mark.unit
def test_the_fat_account_refuses_an_overdraft() -> None:
    source, destination = FatAccount('Alice', Money(100)), FatAccount('Bob', Money(0))

    with pytest.raises(InsufficientFundsError):
        source.transfer_to(destination, Money(5000))


@pytest.mark.unit
def test_the_account_keeps_its_identity() -> None:
    """One cell of the identity row in `APPROACHES.md`, and the cheap one.

    Nothing ever stands in for the account here, because the entity runs the
    transfer itself. Identity is intact for the same reason there are no roles.
    """
    source, destination = FatAccount('Alice', Money(1000)), FatAccount('Bob', Money(0))
    before = id(source)

    source.transfer_to(destination, Money(250))

    assert id(source) == before
    assert isinstance(source, FatAccount)
