"""Design 2: the account emptied of behaviour, and the procedure that moves its attributes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from banking.data.account import InsufficientFundsError

if TYPE_CHECKING:
    from banking.data.money import Money


class AnemicAccount:
    """Version 2, first half: the account with no behaviour left.

    The corrective reaction to `FatAccount`. The account no longer knows about
    transfers, but it no longer does anything at all: it is a record.
    """

    def __init__(self, holder: str, balance: Money) -> None:
        """Open the account."""
        self.holder = holder
        self.balance = balance


class TransferService:
    """Version 2, second half: a procedure in the shape of a class.

    The common form in line-of-business systems. It reads and reassigns
    another object's attributes from the outside, which is what encapsulation
    exists to prevent; the surrounding class does not change that.

    In neither version do "source" and "destination" exist as objects. They
    are parameter names, and they cease to exist when the function returns.
    """

    def transfer(self, source: AnemicAccount, destination: AnemicAccount, amount: Money) -> None:
        """Move `amount` from `source` to `destination`."""
        if source.balance < amount:
            raise InsufficientFundsError(source.holder)
        source.balance = source.balance - amount
        destination.balance = destination.balance + amount
