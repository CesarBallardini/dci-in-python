"""Design 1: the transfer placed on the entity it moves money out of."""

from __future__ import annotations

from typing import TYPE_CHECKING

from banking.data.account import InsufficientFundsError

if TYPE_CHECKING:
    from banking.data.money import Money


class FatAccount:
    """Version 1: the account that knows too much.

    Readable, and the form most people write first. The cost appears over
    time: this account now knows what a transfer is, and will go on to know
    about fees, daily limits, posting hours and frozen accounts. A use case
    has been placed on an entity that predates it and will outlast it, and
    none of those rules describe what an account is.
    """

    def __init__(self, holder: str, balance: Money) -> None:
        """Open the account."""
        self.holder = holder
        self.balance = balance

    def transfer_to(self, destination: FatAccount, amount: Money) -> None:
        """Move `amount` to `destination`."""
        if self.balance < amount:
            raise InsufficientFundsError(self.holder)
        self.balance = self.balance - amount
        destination.balance = destination.balance + amount
