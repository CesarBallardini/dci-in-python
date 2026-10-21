"""Data: what an account is. It has no knowledge of transfers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from banking.data.money import Money, MoneyLike


class AccountLike[M: MoneyLike = Money](Protocol):
    """Everything a transfer needs of whatever is playing an account.

    The protocol is structural, so a class satisfies it without referring to
    it: `Account`, a slotted class, a frozen dataclass, an ORM entity and a
    pydantic model all match. It is the implicit contract of the account roles
    written down once, where a type checker can use it: the roles annotate
    their `self` with it.

    Generic in the kind of amount it holds, so that `TransferAmount` can say
    "an account holding amounts like me" without naming `Money`. The default
    makes a bare `AccountLike` mean `AccountLike[Money]`, which is what every
    caller outside the roles wants.

    `holder` and `balance` are read-only members, because reading is all a role
    does with them. Whether they can be assigned is the data object's concern,
    and requiring mutability here would exclude every immutable entity for no
    benefit.

    The `/` makes the amount positional-only. Without it, a conforming account
    would have to name that parameter `amount` exactly, and an ordinary
    `def debit(self, m)` would not match. These methods are never called by
    keyword, so requiring a particular parameter name would constrain the
    domain for no reason.
    """

    @property
    def holder(self) -> str:
        """Who the account belongs to."""
        ...

    @property
    def balance(self) -> M:
        """The current balance."""
        ...

    def debit(self, amount: M, /) -> None:
        """Remove `amount` from the balance."""
        ...

    def credit(self, amount: M, /) -> None:
        """Add `amount` to the balance."""
        ...


class InsufficientFundsError(Exception):
    """Raised when an account cannot cover the amount a use case asks of it.

    Defined alongside the data because it has no better home. Note that it is
    raised by the `SourceAccount` role, never by `Account` itself.
    """


class Account:
    """An account: a holder and a balance, and the two things it does to itself.

    `debit` and `credit` are not business rules; they are what an account can
    do to itself. There is deliberately no overdraft check: the floor of a
    balance is not a property of the account (zero for a savings account, minus
    the agreed limit for a checking account, and fees or court orders apply
    regardless). How much may leave is decided by the use case.

    This is neither a `__slots__` class nor a frozen dataclass, which is a
    requirement rather than an oversight. Role binding under `Context`
    reassigns `__class__`, and both of those forms make that illegal. See
    `tests/unit/test_limits.py`.
    """

    def __init__(self, holder: str, balance: Money) -> None:
        """Open an account for `holder` holding `balance`."""
        self.holder = holder
        self.balance = balance

    def debit(self, amount: Money) -> None:
        """Remove `amount`. No overdraft check; that belongs to the use case."""
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        """Add `amount`."""
        self.balance = self.balance + amount

    def __repr__(self) -> str:
        """`Account('Alice', 750)`: the amount only, without its currency label."""
        return f'Account({self.holder!r}, {self.balance.amount})'
