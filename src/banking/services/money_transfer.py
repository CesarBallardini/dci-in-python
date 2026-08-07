"""The same use case as a service, written as close to DCI as Python allows.

`banking.alternatives.TransferService` is the conventional service: it reaches
into two objects from the outside and moves their attributes around. This
module keeps everything DCI provides except the one operation that carries the
limitations, and is meant to be read alongside
`banking.contexts.money_transfer`.

What is kept:

* **The use case is an object.** `TransferRoles` is created when the transfer
  starts and discarded when it ends. It is DCI's Context without role binding.
* **The roles are named objects.** `SourceAccountRole` and
  `DestinationAccountRole` exist as classes, rather than being parameter names
  that disappear when the function returns.
* **A role reaches its peers through `TransferRoles`, never directly.** No role
  holds a reference to another participant's data object.
* **The script is in one place**, and the role bodies are nearly identical to
  the DCI ones. The forwarding properties exist so that a role can still write
  `self.balance` and `self.debit(...)`.
* **The data objects are unchanged.** `Account` learns nothing: the roles
  require `banking.data.account.AccountLike`, the same structural protocol the
  DCI version uses.

One thing is given up: the data object never becomes the role.
`SourceAccountRole` holds an account rather than being one, so
`isinstance(role, Account)` is `False`.

That is the Decorator identity problem. What distinguishes this from
`banking.alternatives.SourceWrapper` is the discipline around it. There is no
`__getattr__` catch-all presenting the role as the account, only the three
members the role uses; and the role objects are strictly internal, built inside
`transfer()`, never returned, stored, compared, or used where `isinstance` or
hashing applies. A wrapper that cannot leave the method that built it cannot be
mistaken for the object it wraps.

In exchange, this service avoids every limitation the mechanism has. It works
with all five domain-object styles, including the three where class binding
fails outright (`__slots__`, frozen dataclasses, declaratively mapped ORM
entities); two concurrent transfers over the same account both succeed; and
both type checkers read it with no casts and no suppressions. See
`tests/unit/test_money_transfer_service.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from banking.data.account import InsufficientFundsError

if TYPE_CHECKING:
    from banking.data.account import AccountLike
    from banking.data.money import Money


class SourceAccountRole:
    """Role played by the account the money leaves from."""

    def __init__(self, account: AccountLike, roles: TransferRoles) -> None:
        """Bind this role to `account` for the duration of this transfer."""
        self.account = account
        self.roles = roles

    # Deliberately narrow, and deliberately not `__getattr__`: only the members
    # the role uses, so it reads like a DCI role without presenting itself as
    # the account.
    @property
    def balance(self) -> Money:
        """The balance of the account playing this role."""
        return self.account.balance

    @property
    def holder(self) -> str:
        """The holder of the account playing this role."""
        return self.account.holder

    def debit(self, amount: Money) -> None:
        """Remove `amount` from the account playing this role."""
        self.account.debit(amount)

    def transfer(self) -> None:
        """The interaction. Compare with `banking.roles.money_transfer`.

        Raises:
            InsufficientFundsError: if the balance does not cover the amount.
        """
        if not self.roles.amount.available_in(self):
            raise InsufficientFundsError(self.holder)
        self.roles.amount.withdraw_from(self)
        self.roles.destination.receive()


class DestinationAccountRole:
    """Role played by the account the money arrives at."""

    def __init__(self, account: AccountLike, roles: TransferRoles) -> None:
        """Bind this role to `account` for the duration of this transfer."""
        self.account = account
        self.roles = roles

    def credit(self, amount: Money) -> None:
        """Add `amount` to the account playing this role."""
        self.account.credit(amount)

    def receive(self) -> None:
        """Take in whatever the transfer is moving."""
        self.roles.amount.deposit_into(self)


class TransferAmountRole:
    """Role played by the sum being moved: the third role, retained here.

    Dropping the binding mechanism does not require dropping the modelling.
    The amount remains a participant with a part of its own, rather than an
    argument passed between functions.
    """

    def __init__(self, money: Money, roles: TransferRoles) -> None:
        """Bind this role to `money` for the duration of this transfer."""
        self.money = money
        self.roles = roles

    def available_in(self, account: SourceAccountRole) -> bool:
        """Whether `account` holds at least this much."""
        return account.balance >= self.money

    def withdraw_from(self, account: SourceAccountRole) -> None:
        """Leave `account`."""
        account.debit(self.money)

    def deposit_into(self, account: DestinationAccountRole) -> None:
        """Arrive at `account`."""
        account.credit(self.money)


class TransferRoles:
    """The use case, reified: which object plays which part, for its duration.

    DCI's Context without role binding. It assigns the parts in `__init__`,
    and they are discarded when it is collected. Nothing outside
    `MoneyTransferService.transfer()` ever holds one.
    """

    def __init__(self, source: AccountLike, destination: AccountLike, amount: Money) -> None:
        """Cast `source`, `destination` and `amount` for one transfer."""
        self.source = SourceAccountRole(source, self)
        self.destination = DestinationAccountRole(destination, self)
        self.amount = TransferAmountRole(amount, self)


class MoneyTransferService:
    """A service on the outside, a set of roles on the inside.

    Stateless and reusable, as a service is expected to be. The per-use-case
    object is the `TransferRoles`, built and discarded within each call, so
    the service holds no state between transfers.
    """

    def transfer(self, source: AccountLike, destination: AccountLike, amount: Money) -> None:
        """Move `amount` from `source` to `destination`.

        The roles do not appear in this signature and are never visible to
        the caller.

        Raises:
            InsufficientFundsError: if `source` cannot cover `amount`.
        """
        TransferRoles(source, destination, amount).source.transfer()
