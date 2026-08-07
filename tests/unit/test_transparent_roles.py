"""`TransparentContext`: the synthesized class carrying the data class's name.

Under `Context`, `type(a)` reports `Account@SourceAccount`, a class that exists
in no source file. `TransparentContext` changes only the labels: same MRO, same
`isinstance`, and the same failures wherever `Context` fails.

The tests below check the two halves separately. The name has to reach the
messages CPython builds from `tp_name`, which a metaclass alone cannot achieve;
and the underlying classes have to remain reachable, which is what the
metaclass provides.
"""

from __future__ import annotations

import pickle
from typing import TYPE_CHECKING, cast

import pytest

from banking.contexts.money_transfer import MoneyTransferContext, TransparentMoneyTransferContext
from banking.data.account import Account, InsufficientFundsError
from banking.data.money import Money
from banking.roles.money_transfer import SourceAccount

if TYPE_CHECKING:
    from banking.dci import RoleClass

# ---------------------------------------------------------------------------
# It is the same use case, bound the same way
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_it_moves_the_money(alice: Account, bob: Account) -> None:
    """Relabelling a class does not change what the script does."""
    TransparentMoneyTransferContext(alice, bob, Money(250)).execute()

    assert (alice.balance, bob.balance) == (Money(750), Money(250))


@pytest.mark.unit
def test_it_refuses_a_transfer_beyond_the_balance(alice: Account, bob: Account) -> None:
    """Same guard, same refusal."""
    with pytest.raises(InsufficientFundsError):
        TransparentMoneyTransferContext(alice, bob, Money(5000)).execute()


@pytest.mark.unit
def test_the_binding_is_a_real_binding(alice: Account, bob: Account) -> None:
    """Same MRO and same identity as `Context` -- only the labels differ."""
    with TransparentMoneyTransferContext(alice, bob, Money(10)):
        synthesized = type(alice)

        assert synthesized.__mro__[1] is SourceAccount
        assert synthesized.__mro__[2] is Account
        assert isinstance(alice, Account)
        assert hasattr(alice, 'transfer')

    assert type(alice) is Account


# ---------------------------------------------------------------------------
# The half a metaclass cannot do: the name has to reach `tp_name`
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_type_answers_to_the_data_class_name(alice: Account, bob: Account) -> None:
    """What `type()` reports, side by side with the binder that does not bother."""
    with MoneyTransferContext(alice, bob, Money(10)):
        assert type(alice).__name__ == 'Account@SourceAccount'

    with TransparentMoneyTransferContext(alice, bob, Money(10)):
        assert type(alice).__name__ == 'Account'
        assert type(alice).__qualname__ == Account.__qualname__
        assert type(alice).__module__ == Account.__module__


@pytest.mark.unit
def test_the_name_reaches_the_error_messages(alice: Account, bob: Account) -> None:
    """Why the class is renamed rather than given a metaclass `__name__`.

    CPython builds `AttributeError` out of the type's `tp_name`, which follows
    `__name__` and is out of reach of anything a metaclass can override. So
    this is where a `__name__` property on the metaclass would have leaked the
    synthesized name and a plain rename does not.
    """
    # Reached by name rather than written as `alice.no_such_attribute`: the
    # attribute exists on neither class in the mix, which is what the test is
    # about, so a lookup by name is what is actually being asked for, and it
    # is the form that does not require silencing a type checker.
    missing = 'no_such_attribute'

    with MoneyTransferContext(alice, bob, Money(10)), pytest.raises(AttributeError, match='Account@SourceAccount'):
        getattr(alice, missing)

    with TransparentMoneyTransferContext(alice, bob, Money(10)), pytest.raises(AttributeError) as caught:
        getattr(alice, missing)

    assert "'Account' object has no attribute" in str(caught.value)
    assert '@' not in str(caught.value)


# ---------------------------------------------------------------------------
# The half the metaclass is for: the disguise stays inspectable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_disguise_is_inspectable(alice: Account, bob: Account) -> None:
    """The renamed class still reports the two classes it was built from."""
    with TransparentMoneyTransferContext(alice, bob, Money(10)):
        # Statically `type[Account]`; in fact an instance of `RoleClass`, which
        # is the runtime fact this whole test is about. The cast is the
        # question a caller would ask, in the form a checker can read.
        synthesized = cast('RoleClass', type(alice))

        assert synthesized.__dci_data__ is Account
        assert synthesized.__dci_role__ is SourceAccount
        assert repr(synthesized) == f"<class '{Account.__module__}.Account' playing 'SourceAccount'>"


@pytest.mark.unit
def test_the_real_class_is_untouched(alice: Account, bob: Account) -> None:
    """Relabelling the synthesized class must not relabel `Account` itself."""
    with TransparentMoneyTransferContext(alice, bob, Money(10)):
        assert type(alice) is not Account

    assert Account.__name__ == 'Account'
    assert repr(Account) == f"<class '{Account.__module__}.Account'>"


# ---------------------------------------------------------------------------
# Everything `Context` cannot do, this one still cannot do
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_two_live_contexts_still_collide() -> None:
    """A label change fixes nothing structural, and it is not meant to.

    The object still has exactly one `__class__` slot and two contexts still
    want different things in it.
    """
    shared = Account('Erin', Money(1_000_000))
    first = TransparentMoneyTransferContext(shared, Account('Frank', Money(0)), Money(10))
    second = TransparentMoneyTransferContext(shared, Account('Grace', Money(0)), Money(20))

    first.__enter__()
    try:
        with pytest.raises(TypeError, match=r'[Cc]onsistent method resolution\s+order'):
            second.__enter__()
    finally:
        first.__exit__()


@pytest.mark.unit
def test_pickle_still_refuses_but_says_something_better(alice: Account, bob: Account) -> None:
    """Still unpicklable, and now for a reason that names a real class.

    `Context` produces "cannot find `Account@SourceAccount`", which sends you
    looking for a class that was never written. This one produces "not the same
    object as `banking.data.account.Account`", which is the actual situation.
    """
    with TransparentMoneyTransferContext(alice, bob, Money(10)), pytest.raises(pickle.PicklingError) as caught:
        pickle.dumps(alice)

    assert 'not the same object as' in str(caught.value)
