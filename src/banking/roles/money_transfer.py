"""Interaction: the three roles of a money transfer, and the script between them.

`SourceAccount` is worth reading closely, because the whole idea is in those
few lines. It inherits from nothing and is never instantiated. It uses
`self.holder` without defining it, and `TransferAmount` asks the account for
`balance`, `debit()` and `credit()` without knowing what an account is. They
are classes written to be attached to another object for the duration of a
context.

What a role knows and does not know is the point. It has no knowledge of
which class will play it, but it does require a protocol from that class:
`holder`, `balance`, `debit()`, `credit()`. That contract is all the role
demands, and it is the property Reenskaug wanted from Simula in 1970 and did
not get -- components that communicate through a standard protocol and are
opaque internally. It is written down as the type of each role's `self`:
`AccountLike` for the two accounts, and for the amount a type variable bound
to `MoneyLike`. To reach its peers, a role asks the context rather than
holding a reference: a role knows the other *role*, not the object playing it.

`TransferAmount` is the third role. The Artima paper's example uses two, but
the architecture chapter notes that "one possible mental model has three
Roles: Source Account, Destination Account, and Transfer Amount". The amount
is not a domain entity and has no table, and it is still a role, which shows
that a role is a part in a script rather than a row with methods.

The names come from the user's description of the task, not from a class
diagram: someone describing moving money between accounts will say the
source, the destination, and the amount.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from banking.data.account import AccountLike, InsufficientFundsError
from banking.data.money import MoneyLike
from banking.dci import context

if TYPE_CHECKING:
    from banking.data.money import Money


class SourceAccount:
    """Role played by the account the money leaves from."""

    def transfer(self: AccountLike) -> None:
        """The script, in the order the user would describe it.

        Note the absence of parameters. The amount is not an argument passed
        between functions; it is a participant with a part of its own, and the
        source reaches it the same way it reaches the destination.

        `self` is annotated with what the role requires of its player rather
        than left as `SourceAccount`, because at runtime it is never a
        `SourceAccount`: it is an `Account@SourceAccount`, or an `Account` with
        the method written into its `__dict__`.

        Raises:
            InsufficientFundsError: if the balance does not cover the amount.
        """
        transfer = context(_RunningTransfer)
        if not transfer.amount.available_in(self):
            raise InsufficientFundsError(self.holder)
        transfer.amount.withdraw_from(self)
        transfer.destination.receive()


class DestinationAccount:
    """Role played by the account the money arrives at."""

    def receive(self: AccountLike) -> None:
        """Take in whatever the transfer is moving."""
        context(_RunningTransfer).amount.deposit_into(self)


class TransferAmount:
    """Role played by the sum of money being moved.

    This role, not `Account`, is where "can this much leave that balance" is
    decided. Whether a balance may go below zero is a property of this use
    case, not of either account.

    `self` is a type variable rather than `Money`: both type checkers reject
    `self: Money`, because `Money` is not a supertype of `TransferAmount`, and
    accept a type variable bound to a protocol. Binding it to the account's own
    type parameter is what says "an account holding amounts like this one", and
    it is why no `cast` is needed to hand `self` to `debit` and `credit`.
    """

    def available_in[M: MoneyLike](self: M, account: AccountLike[M]) -> bool:
        """Whether `account` holds at least this much."""
        return account.balance >= self

    def withdraw_from[M: MoneyLike](self: M, account: AccountLike[M]) -> None:
        """Leave `account`."""
        account.debit(self)

    def deposit_into[M: MoneyLike](self: M, account: AccountLike[M]) -> None:
        """Arrive at `account`."""
        account.credit(self)


# What each participant looks like while it plays its part: the data object's
# protocol and the role's methods together. Python has no intersection type,
# so "an `AccountLike` that is also a `SourceAccount`" is written out by hand.
# These are what a role sees of its peers, and what a context sees of a
# participant once `__enter__` has bound it.


class SourceAccountPlayer(AccountLike, Protocol):
    """An account while it plays `SourceAccount`."""

    def transfer(self) -> None:
        """See `SourceAccount.transfer`."""
        ...


class DestinationAccountPlayer(AccountLike, Protocol):
    """An account while it plays `DestinationAccount`."""

    def receive(self) -> None:
        """See `DestinationAccount.receive`."""
        ...


class TransferAmountPlayer(MoneyLike, Protocol):
    """An amount while it plays `TransferAmount`."""

    def available_in(self, account: AccountLike[Money], /) -> bool:
        """See `TransferAmount.available_in`."""
        ...

    def withdraw_from(self, account: AccountLike[Money], /) -> None:
        """See `TransferAmount.withdraw_from`."""
        ...

    def deposit_into(self, account: AccountLike[Money], /) -> None:
        """See `TransferAmount.deposit_into`."""
        ...


class _RunningTransfer(Protocol):
    """What a transfer role requires of the context it is running in.

    Declared here rather than importing the concrete `MoneyTransferContext`,
    so that the dependency points the intended way: a context knows its roles,
    a role does not know its contexts.

    The participants are typed as players, not as roles: a role's peer is an
    account or an amount *playing* a part, so it has both the data object's
    protocol and the role's methods. `context(_RunningTransfer)` is what types
    them without a `cast`.
    """

    source: SourceAccountPlayer
    destination: DestinationAccountPlayer
    amount: TransferAmountPlayer
