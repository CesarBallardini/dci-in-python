"""The service: same use case, same script, without the mechanism's limits.

Two things are checked here. First, that it performs the same job as
`MoneyTransferContext`, with the same outcomes and the same refusals. Second,
and the reason it exists, that none of the limits `tests/unit/test_limits.py`
records for class binding applies: the domain-object styles that cannot take a
role are transferred without error, and two concurrent transfers over one
account both succeed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import attrs
import pytest
from pydantic import BaseModel

from banking.contexts.money_transfer import MoneyTransferContext
from banking.data.account import Account, AccountLike, InsufficientFundsError
from banking.data.money import Money
from banking.services.money_transfer import MoneyTransferService, TransferRoles


class SlottedAccount:
    """One of the styles DCI cannot bind a role to."""

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
    """Ditto -- a frozen dataclass refuses every `__setattr__`."""

    holder: str
    balance: Money

    def debit(self, amount: Money) -> None:
        object.__setattr__(self, 'balance', self.balance - amount)

    def credit(self, amount: Money) -> None:
        object.__setattr__(self, 'balance', self.balance + amount)


@attrs.define
class AttrsAccount:
    """Ditto -- `slots=True` is `@define`'s default."""

    holder: str
    balance: Money

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


class PydanticAccount(BaseModel):
    """This one DCI can handle too, kept so the sweep covers the whole table."""

    holder: str
    balance: Money
    model_config = {'arbitrary_types_allowed': True}

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


class SlowAccount(Account):
    """An account whose debit is slow enough to guarantee the threads overlap."""

    def debit(self, amount: Money) -> None:
        time.sleep(0.2)
        super().debit(amount)


def pair(style: type, holder_balance: int = 1000) -> tuple[AccountLike, AccountLike]:
    """Two accounts of the given style, ready to transfer between."""
    if style is PydanticAccount:
        return (
            PydanticAccount(holder='Alice', balance=Money(holder_balance)),
            PydanticAccount(holder='Bob', balance=Money(0)),
        )
    return style('Alice', Money(holder_balance)), style('Bob', Money(0))


@pytest.mark.unit
def test_it_moves_the_money(alice: Account, bob: Account) -> None:
    MoneyTransferService().transfer(alice, bob, Money(250))

    assert (alice.balance, bob.balance) == (Money(750), Money(250))


@pytest.mark.unit
def test_it_refuses_a_transfer_beyond_the_balance(alice: Account, bob: Account) -> None:
    with pytest.raises(InsufficientFundsError):
        MoneyTransferService().transfer(alice, bob, Money(5000))

    assert (alice.balance, bob.balance) == (Money(1000), Money(0))


@pytest.mark.unit
def test_the_service_is_stateless_and_reusable(alice: Account, bob: Account) -> None:
    service = MoneyTransferService()

    service.transfer(alice, bob, Money(100))
    service.transfer(alice, bob, Money(100))
    service.transfer(bob, alice, Money(50))

    assert (alice.balance, bob.balance) == (Money(850), Money(150))


@pytest.mark.unit
@pytest.mark.parametrize('style', [Account, SlottedAccount, FrozenAccount, AttrsAccount, PydanticAccount])
def test_it_works_with_every_style_of_domain_object(style: type) -> None:
    """The payoff: three of these five cannot take a DCI role at all."""
    source, destination = pair(style)

    MoneyTransferService().transfer(source, destination, Money(250))

    assert (source.balance, destination.balance) == (Money(750), Money(250))


@pytest.mark.unit
@pytest.mark.parametrize(
    ('style', 'message'),
    [
        (SlottedAccount, 'object layout differs'),
        (AttrsAccount, 'object layout differs'),
        (FrozenAccount, "cannot assign to field '__class__'"),
    ],
)
def test_and_dci_refuses_those_same_three(style: type, message: str) -> None:
    """The other half of the comparison, so the contrast is measured both ways.

    Matching on the message, not just on `Exception`: the two failures are
    different, and a test that accepted either would also accept a typo.
    """
    source, destination = pair(style)

    with pytest.raises(Exception, match=message):
        MoneyTransferContext(source, destination, Money(250)).execute()


@pytest.mark.unit
def test_two_concurrent_transfers_over_one_account_both_succeed() -> None:
    """Exactly the scenario that breaks DCI, and here it is uneventful.

    `SlowAccount.debit` sleeps, so the two transfers are genuinely overlapping
    rather than accidentally serialized. Nothing is bound to the account, so
    there is no shared `__class__` for the second transfer to trip over.
    """
    shared = SlowAccount('Erin', Money(1_000_000))
    first, second = Account('Frank', Money(0)), Account('Grace', Money(0))
    failures: list[str] = []
    service = MoneyTransferService()

    def transfer_to(destination: Account) -> None:
        try:
            service.transfer(shared, destination, Money(10))
        except Exception as exc:  # the point is that nothing lands here
            failures.append(type(exc).__name__)

    threads = [
        threading.Thread(target=transfer_to, args=(first,)),
        threading.Thread(target=transfer_to, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert failures == []
    assert (first.balance, second.balance) == (Money(10), Money(10))


@pytest.mark.unit
def test_the_caller_keeps_holding_the_same_account(alice: Account, bob: Account) -> None:
    """The identity concession is real but contained: nothing wrapped escapes.

    The caller hands in an `Account` and goes on holding that same `Account`.
    The role objects live and die inside `transfer()`.
    """
    before = id(alice)

    MoneyTransferService().transfer(alice, bob, Money(250))

    assert id(alice) == before
    assert type(alice) is Account


@pytest.mark.unit
def test_the_role_is_honest_about_not_being_the_account(alice: Account, bob: Account) -> None:
    """And where DCI genuinely wins is still where DCI wins -- stated outright.

    Inside a DCI context, `alice` *is* a `SourceAccount` and stays an `Account`.
    Here the role is a separate object that holds the account. That is the one
    thing given up, and it is only safe because nothing outside the service
    ever sees this object.
    """
    roles = TransferRoles(alice, bob, Money(10))

    assert not isinstance(roles.source, Account)
    assert roles.source.account is alice
    assert roles.source.balance == alice.balance
