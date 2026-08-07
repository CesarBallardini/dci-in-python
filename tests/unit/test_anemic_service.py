"""Design 2: the record with no behaviour, and the procedure that manipulates it.

The money moves. What this records is that neither "source" nor "destination"
exists as an object: they are parameter names, and they cease to exist when
`transfer` returns.
"""

from __future__ import annotations

import pytest

from banking.alternatives import AnemicAccount, TransferService
from banking.data.money import Money


@pytest.mark.unit
def test_the_service_transfers() -> None:
    source, destination = AnemicAccount('Alice', Money(1000)), AnemicAccount('Bob', Money(0))

    TransferService().transfer(source, destination, Money(250))

    assert (source.balance, destination.balance) == (Money(750), Money(250))


@pytest.mark.unit
def test_the_accounts_keep_their_identity() -> None:
    """The other cheap cell of the identity row in `APPROACHES.md`.

    The service reaches into the accounts from outside rather than standing in
    for them, so identity survives -- which is what makes designs 4 and 5, the
    ones that do stand in, the only two that give it up.
    """
    source, destination = AnemicAccount('Alice', Money(1000)), AnemicAccount('Bob', Money(0))
    before = (id(source), id(destination))

    TransferService().transfer(source, destination, Money(250))

    assert (id(source), id(destination)) == before
