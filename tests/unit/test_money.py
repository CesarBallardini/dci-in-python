"""The Money value object: equality by value, and no mixing kinds of money."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from banking.data.money import CurrencyMismatchError, Money

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.unit
def test_equality_is_by_value() -> None:
    assert Money(250, 'ARS') == Money(250, 'ARS')
    assert Money(250, 'ARS') != Money(250, 'USD')
    assert Money(250, 'ARS') != Money(100, 'ARS')


@pytest.mark.unit
def test_it_is_hashable_like_a_value() -> None:
    assert len({Money(250, 'ARS'), Money(250, 'ARS'), Money(250, 'USD')}) == 2


@pytest.mark.unit
def test_arithmetic_returns_new_instances() -> None:
    original = Money(1000)

    result = original - Money(250)

    assert result == Money(750)
    assert original == Money(1000)


@pytest.mark.unit
def test_ordering_within_one_currency() -> None:
    assert Money(100) < Money(250)
    assert Money(250) >= Money(250)


@pytest.mark.unit
@pytest.mark.parametrize('operation', [lambda a, b: a + b, lambda a, b: a - b, lambda a, b: a < b])
def test_different_kinds_of_money_never_mix(operation: Callable[[Money, Money], object]) -> None:
    with pytest.raises(CurrencyMismatchError):
        operation(Money(100, 'ARS'), Money(100, 'USD'))


@pytest.mark.unit
def test_a_balance_may_go_negative() -> None:
    """Money has no floor: the floor, if any, is a rule of some use case."""
    assert (Money(100) - Money(500)).amount == -400
