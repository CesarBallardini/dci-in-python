"""Data: an amount of money. It has no knowledge of transfers either."""

from __future__ import annotations

import functools
from typing import Protocol, Self


class MoneyLike(Protocol):
    """What a transfer needs of an amount: that it can be compared with another.

    Structural, like `banking.data.account.AccountLike`, and as small as the
    roles allow: `TransferAmount` asks a balance whether it covers the amount,
    and hands the amount to `debit` and `credit` untouched. Arithmetic is the
    account's business, so it is not required here.

    `Money` satisfies it without naming it; `functools.total_ordering` supplies
    the `__ge__`.
    """

    def __ge__(self, other: Self, /) -> bool:
        """Whether this amount is at least `other`."""
        ...


class CurrencyMismatchError(Exception):
    """Raised when two amounts of different kinds of money are combined or compared.

    This is a property of money rather than of a use case: pesos and dollars
    do not add up in any context, so the check belongs here rather than in a
    role.
    """


@functools.total_ordering
class Money:
    """A value object: an amount, and a label saying what kind of money it is.

    The label is the currency -- `'ARS'`, `'USD'`, and so on. Two `Money` with
    the same amount and different labels are different values and refuse to be
    added, subtracted or compared.

    `amount` is in minor units (cents), so no float ever touches money and
    `Money(250, 'ARS')` is $2,50.

    A value object, so equality is by value and it is hashable. Immutable by
    convention: `__add__` and `__sub__` return new instances and nothing ever
    mutates one in place.

    Deliberately not written as `@dataclass(frozen=True)`, which would be the
    idiomatic form. A frozen dataclass rejects every `__setattr__`, `__class__`
    included, so it could not play the `TransferAmount` role under `Context`.
    `tests/unit/test_limits.py::test_a_frozen_value_object_cannot_play_the_amount`
    asserts this. The cause differs from the `__slots__` case -- there the
    object layout is what blocks reassignment -- but the outcome is the same.
    """

    def __init__(self, amount: int, currency: str = 'ARS') -> None:
        """`amount` minor units of `currency`."""
        self.amount = amount
        self.currency = currency

    def _same_kind(self, other: Money) -> Money:
        """Return `other`, or raise if it is a different kind of money."""
        if self.currency != other.currency:
            raise CurrencyMismatchError(f'{self.currency} vs {other.currency}')
        return other

    def __add__(self, other: Money) -> Money:
        """A new amount: this one plus `other`."""
        return Money(self.amount + self._same_kind(other).amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        """A new amount: this one minus `other`."""
        return Money(self.amount - self._same_kind(other).amount, self.currency)

    def __eq__(self, other: object) -> bool:
        """Same amount and same kind of money."""
        if not isinstance(other, Money):
            return NotImplemented
        return (self.amount, self.currency) == (other.amount, other.currency)

    def __lt__(self, other: Money) -> bool:
        """Ordering within one currency. `functools.total_ordering` derives the rest."""
        return self.amount < self._same_kind(other).amount

    def __hash__(self) -> int:
        """Hashable, because this is a value object."""
        return hash((self.amount, self.currency))

    def __repr__(self) -> str:
        """`Money(250, 'ARS')`."""
        return f'Money({self.amount}, {self.currency!r})'
