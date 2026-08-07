"""What distinguishes DCI from a service: roles are temporary and contextual.

A role exists only while its context runs, the same object can play different
roles in different contexts, and binding preserves object identity. The third
role, `TransferAmount`, is covered here as well: it shows that a role need not
correspond to a domain entity.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from banking.contexts.money_transfer import MoneyTransferContext
from banking.data.account import Account
from banking.data.money import Money
from banking.dci import context
from banking.roles.money_transfer import SourceAccount


@pytest.mark.unit
def test_the_role_does_not_exist_before_the_context(alice: Account) -> None:
    assert not hasattr(alice, 'transfer')


@pytest.mark.unit
def test_every_participant_gets_its_role_inside_the_context(alice: Account, bob: Account) -> None:
    amount = Money(10)

    with MoneyTransferContext(alice, bob, amount):
        assert hasattr(alice, 'transfer')
        assert hasattr(bob, 'receive')
        assert hasattr(amount, 'withdraw_from')


@pytest.mark.unit
def test_the_role_is_gone_again_after_the_context(alice: Account, bob: Account) -> None:
    amount = Money(10)

    with MoneyTransferContext(alice, bob, amount):
        pass

    assert not hasattr(alice, 'transfer')
    assert not hasattr(amount, 'withdraw_from')
    assert type(alice).__name__ == 'Account'


@pytest.mark.unit
def test_the_object_is_still_an_account_while_playing_the_role(alice: Account, bob: Account) -> None:
    """Both halves of the claim: the object is the role, and the rest of the system never notices.

    The role is mixed over the real class rather than wrapping it, so the
    object satisfies `isinstance` against both at once. This is the property
    that separates role binding from a wrapper and from a service, and the row
    `APPROACHES.md` marks for DCI alone.
    """
    with MoneyTransferContext(alice, bob, Money(10)):
        assert isinstance(alice, SourceAccount)
        assert isinstance(alice, Account)
        assert type(alice).__name__ == 'Account@SourceAccount'


@pytest.mark.unit
def test_the_amount_plays_a_role_without_being_a_domain_entity(alice: Account, bob: Account) -> None:
    """The third role: a part in the script that corresponds to no table."""
    amount = Money(10)

    with MoneyTransferContext(alice, bob, amount):
        assert type(amount).__name__ == 'Money@TransferAmount'
        assert isinstance(amount, Money)

    assert type(amount).__name__ == 'Money'


@pytest.mark.unit
def test_identity_is_preserved(alice: Account, bob: Account) -> None:
    """Not a wrapper: the same object, before, during and after."""
    before = id(alice)

    with MoneyTransferContext(alice, bob, Money(10)) as ctx:
        assert id(alice) == before
        assert ctx.source is alice

    assert id(alice) == before


@pytest.mark.unit
def test_the_same_account_plays_the_opposite_role_next_time(alice: Account, bob: Account) -> None:
    """A role is played, not owned -- and not one line was added to `Account`."""
    MoneyTransferContext(alice, bob, Money(250)).execute()
    MoneyTransferContext(bob, alice, Money(100)).execute()

    assert (alice.balance, bob.balance) == (Money(850), Money(150))


@pytest.mark.unit
def test_roles_are_released_even_when_the_body_raises(alice: Account, bob: Account) -> None:
    with pytest.raises(RuntimeError), MoneyTransferContext(alice, bob, Money(10)):
        raise RuntimeError('boom')

    assert type(alice).__name__ == 'Account'


@pytest.mark.unit
def test_a_failed_bind_leaves_nothing_behind(alice: Account, bob: Account) -> None:
    """Binding is all-or-nothing, or a half-entered context poisons the thread.

    The amount here cannot take its role, so `__enter__` must undo the two
    accounts it already bound *and* pop itself as the current context. If it
    did not, the next role to call `context()` would get this dead transfer.
    """

    @dataclass(frozen=True)
    class FrozenAccount:
        holder: str
        balance: Money

        def debit(self, amount: Money) -> None:
            object.__setattr__(self, 'balance', self.balance - amount)

        def credit(self, amount: Money) -> None:
            object.__setattr__(self, 'balance', self.balance + amount)

    ctx = MoneyTransferContext(alice, bob, Money(10))
    ctx.destination = FrozenAccount('Heidi', Money(0))

    with pytest.raises(Exception, match="cannot assign to field '__class__'"):
        ctx.__enter__()

    assert type(alice).__name__ == 'Account'
    assert type(bob).__name__ == 'Account'
    with pytest.raises(LookupError):
        context()


@pytest.mark.unit
def test_a_context_refuses_to_be_entered_twice(alice: Account, bob: Account) -> None:
    """A use case in flight is not a nesting construct.

    Silently re-entering would overwrite the token of the first `__enter__`,
    and the outer exit would then reset a token already spent -- surfacing as
    a `Token has already been used once` several frames from the cause.
    """
    ctx = MoneyTransferContext(alice, bob, Money(10))

    with ctx, pytest.raises(RuntimeError, match='not re-entrant'):
        ctx.execute()

    assert type(alice).__name__ == 'Account'


@pytest.mark.unit
def test_the_same_context_can_run_again_once_it_has_finished(alice: Account, bob: Account) -> None:
    """Refusing re-entry is not refusing reuse."""
    ctx = MoneyTransferContext(alice, bob, Money(100))

    ctx.execute()
    ctx.execute()

    assert (alice.balance, bob.balance) == (Money(800), Money(200))


@pytest.mark.unit
def test_the_context_is_reachable_from_inside_and_only_from_inside(alice: Account, bob: Account) -> None:
    ctx = MoneyTransferContext(alice, bob, Money(10))

    with ctx:
        assert context() is ctx

    with pytest.raises(LookupError):
        context()
