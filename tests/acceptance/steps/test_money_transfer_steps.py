"""Step definitions for money_transfer.feature."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from banking.contexts.money_transfer import MoneyTransferContext
from banking.data.account import Account, InsufficientFundsError
from banking.data.money import CurrencyMismatchError, Money

scenarios('../features/money_transfer.feature')


@pytest.fixture
def accounts() -> dict[str, Account]:
    return {}


@dataclass
class CaughtErrorDto:
    """The refusal a `When` step caught, for a `Then` step to name."""

    raised: Exception | None = None


@pytest.fixture
def caught_error() -> CaughtErrorDto:
    return CaughtErrorDto()


@given(parsers.parse('an account "{holder}" with {amount:d} {currency}'))
def an_account(accounts: dict[str, Account], holder: str, amount: int, currency: str) -> None:
    accounts[holder] = Account(holder, Money(amount, currency))


@when(parsers.parse('"{source}" transfers {amount:d} {currency} to "{destination}"'))
def transfers(accounts: dict[str, Account], source: str, amount: int, currency: str, destination: str) -> None:
    MoneyTransferContext(accounts[source], accounts[destination], Money(amount, currency)).execute()


@when(parsers.parse('"{source}" tries to transfer {amount:d} {currency} to "{destination}"'))
def tries_to_transfer(
    accounts: dict[str, Account],
    source: str,
    amount: int,
    currency: str,
    destination: str,
    caught_error: CaughtErrorDto,
) -> None:
    try:
        MoneyTransferContext(accounts[source], accounts[destination], Money(amount, currency)).execute()
    except (InsufficientFundsError, CurrencyMismatchError) as exc:
        caught_error.raised = exc


@then(parsers.parse('"{holder}" has {amount:d} {currency}'))
def has_balance(accounts: dict[str, Account], holder: str, amount: int, currency: str) -> None:
    assert accounts[holder].balance == Money(amount, currency)


@then('it fails for insufficient funds')
def it_fails_for_insufficient_funds(caught_error: CaughtErrorDto) -> None:
    assert isinstance(caught_error.raised, InsufficientFundsError)


@then('it fails because the kinds of money differ')
def it_fails_for_currency_mismatch(caught_error: CaughtErrorDto) -> None:
    assert isinstance(caught_error.raised, CurrencyMismatchError)


@then(parsers.parse('"{holder}" cannot transfer on her own'))
def cannot_transfer_alone(accounts: dict[str, Account], holder: str) -> None:
    assert not hasattr(accounts[holder], 'transfer')
