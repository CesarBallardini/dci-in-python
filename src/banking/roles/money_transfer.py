"""Interaction: the three roles of a money transfer, and the script between them.

`SourceAccount` is worth reading closely, because the whole idea is in those
few lines. It inherits from nothing and is never instantiated. It uses
`self.balance` and `self.debit()` without defining either. It is a class
written to be attached to another object for the duration of a context.

What a role knows and does not know is the point. It has no knowledge of
which class will play it, but it does require a protocol from that class:
`balance` and `debit()`. That implicit contract is all the role demands, and
it is the property Reenskaug wanted from Simula in 1970 and did not get --
components that communicate through a standard protocol and are opaque
internally. To reach its peers, a role asks the context rather than holding a
reference: a role knows the other *role*, not the object playing it.

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

from typing import TYPE_CHECKING, Protocol, cast

from banking.data.account import InsufficientFundsError
from banking.dci import context

if TYPE_CHECKING:
    from banking.data.money import Money


class SourceAccount:
    """Role played by the account the money leaves from."""

    if TYPE_CHECKING:
        # The implicit protocol this role requires of whatever object plays it.
        # None of it exists at runtime: the synthesized `Account@SourceAccount`
        # resolves `balance` and `debit` on the data class in the mix. It is
        # written down because a type checker cannot otherwise read a role, and
        # stating the contract is preferable to suppressing the errors.
        balance: Money
        holder: str

        def debit(self, amount: Money) -> None:
            """Supplied by the data object playing this role."""

    def transfer(self) -> None:
        """The script, in the order the user would describe it.

        Note the absence of parameters. The amount is not an argument passed
        between functions; it is a participant with a part of its own, and the
        source reaches it the same way it reaches the destination.

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

    if TYPE_CHECKING:

        def credit(self, amount: Money) -> None:
            """Supplied by the data object playing this role."""

    def receive(self) -> None:
        """Take in whatever the transfer is moving."""
        context(_RunningTransfer).amount.deposit_into(self)


class TransferAmount:
    """Role played by the sum of money being moved.

    This role, not `Account`, is where "can this much leave that balance" is
    decided. Whether a balance may go below zero is a property of this use
    case, not of either account.
    """

    if TYPE_CHECKING:
        amount: int
        currency: str

    def as_money(self) -> Money:
        """`self`, viewed as the data object playing this role.

        The single place where this role states that a type checker cannot be
        shown a class built at runtime. Every method below goes through it, so
        the cast is made once and named rather than repeated.
        """
        return cast('Money', self)

    def available_in(self, account: SourceAccount) -> bool:
        """Whether `account` holds at least this much."""
        return account.balance >= self.as_money()

    def withdraw_from(self, account: SourceAccount) -> None:
        """Leave `account`."""
        account.debit(self.as_money())

    def deposit_into(self, account: DestinationAccount) -> None:
        """Arrive at `account`."""
        account.credit(self.as_money())


class _RunningTransfer(Protocol):
    """What a transfer role requires of the context it is running in.

    Declared here rather than importing the concrete `MoneyTransferContext`,
    so that the dependency points the intended way: a context knows its roles,
    a role does not know its contexts.

    It exists at runtime, unlike the protocols the roles declare above, because
    it is passed to `context()` as a value: `context(_RunningTransfer)` is what
    types a role's peers without a `cast`.
    """

    source: SourceAccount
    destination: DestinationAccount
    amount: TransferAmount
