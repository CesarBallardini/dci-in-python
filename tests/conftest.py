"""Shared fixtures for the whole test suite."""

from __future__ import annotations

import pytest

from banking.data.account import Account
from banking.data.money import Money


@pytest.fixture
def alice() -> Account:
    """An account with money in it, ready to be a source."""
    return Account('Alice', Money(1000))


@pytest.fixture
def bob() -> Account:
    """An empty account, ready to be a destination."""
    return Account('Bob', Money(0))
