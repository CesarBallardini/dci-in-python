"""The use case itself: does the money move, and does it refuse when it should."""

from __future__ import annotations

import pytest

from banking.contexts.money_transfer import MoneyTransferContext
from banking.data.account import Account, InsufficientFundsError
from banking.data.money import CurrencyMismatchError, Money


@pytest.mark.unit
def test_transfer_moves_the_money(alice: Account, bob: Account) -> None:
    MoneyTransferContext(alice, bob, Money(250)).execute()

    assert (alice.balance, bob.balance) == (Money(750), Money(250))


@pytest.mark.unit
def test_transfer_conserves_the_total(alice: Account, bob: Account) -> None:
    total_before = alice.balance + bob.balance

    MoneyTransferContext(alice, bob, Money(250)).execute()

    assert alice.balance + bob.balance == total_before


@pytest.mark.unit
def test_transfer_beyond_the_balance_is_refused(alice: Account, bob: Account) -> None:
    with pytest.raises(InsufficientFundsError):
        MoneyTransferContext(alice, bob, Money(5000)).execute()


@pytest.mark.unit
def test_a_refused_transfer_moves_nothing(alice: Account, bob: Account) -> None:
    with pytest.raises(InsufficientFundsError):
        MoneyTransferContext(alice, bob, Money(5000)).execute()

    assert (alice.balance, bob.balance) == (Money(1000), Money(0))


@pytest.mark.unit
def test_the_whole_balance_may_leave(alice: Account, bob: Account) -> None:
    MoneyTransferContext(alice, bob, Money(1000)).execute()

    assert (alice.balance, bob.balance) == (Money(0), Money(1000))


@pytest.mark.unit
def test_the_kinds_of_money_have_to_agree(alice: Account, bob: Account) -> None:
    with pytest.raises(CurrencyMismatchError):
        MoneyTransferContext(alice, bob, Money(250, 'USD')).execute()


@pytest.mark.unit
def test_the_overdraft_rule_belongs_to_the_use_case_not_the_account(alice: Account) -> None:
    """`Account` itself never refuses: a fee or a court order goes through."""
    alice.debit(Money(5000))

    assert alice.balance == Money(-4000)
