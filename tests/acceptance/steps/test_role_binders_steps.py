"""Step definitions for role_binders.feature.

`APPROACHES.md` contains a table with four columns and ten rows. Tables are
easy to write and easy to get wrong, so every cell of it is an example row
here. Three cells carry a qualification a table cannot express: the locking
binder serializes *across threads* but re-enters within one, twice over, and
the instance binder declines to bind a dunder rather than binding one that
could never run.
"""

from __future__ import annotations

import pickle
import threading
import time
import types
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from banking.contexts.money_transfer import (
    InstanceMoneyTransferContext,
    MoneyTransferContext,
    SerializedMoneyTransferContext,
    TransparentMoneyTransferContext,
)
from banking.data.account import Account
from banking.data.money import Money
from banking.dci import Context, InstanceContext, context

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Protocol, Self

    from banking.data.account import AccountLike

    class RunningRole(Protocol):
        """The least a scenario needs: something it can hold open and close by hand.

        `BaseContext` is the wrong type for the tables below -- it deliberately
        knows nothing about any particular use case -- so what the scenarios
        need is named structurally instead. Same move as
        `banking.roles.money_transfer._RunningTransfer`, for the same reason.
        """

        def __enter__(self) -> Self:
            """Bind the roles."""
            ...

        def __exit__(self, *exc_info: object) -> bool:
            """Unbind the roles."""
            ...

    class RunningUseCase(RunningRole, Protocol):
        """The same, plus the transfer script: what the four binders are combined with."""

        def run_script(self) -> None:
            """Run the interaction with the roles already bound."""
            ...

        def execute(self) -> None:
            """Bind, run, unbind."""
            ...

    class TransferBinder(Protocol):
        """One of the four context classes, seen as "cast three participants"."""

        def __call__(self, source: AccountLike, destination: AccountLike, amount: Money) -> RunningUseCase:
            """Construct one transfer."""
            ...

    class AmountBinder(Protocol):
        """A context over a single participant, for the special-method scenario.

        It returns only a `RunningRole`, because these two contexts have no
        script: what is measured is whether the role's method was bound, not
        what it then does.
        """

        def __call__(self, amount: Money) -> RunningRole:
            """Construct one comparison."""
            ...


scenarios('../features/role_binders.feature')

BINDERS: dict[str, TransferBinder] = {
    'class': MoneyTransferContext,
    'transparent': TransparentMoneyTransferContext,
    'serialized': SerializedMoneyTransferContext,
    'instance': InstanceMoneyTransferContext,
}


class SlottedAccount:
    """No instance dictionary and a layout of its own: no binder can bind to it."""

    __slots__ = ('balance', 'holder')

    def __init__(self, holder: str, balance: Money) -> None:
        self.holder = holder
        self.balance = balance

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


class ComparableAmount:
    """A role that would make the object playing it comparable."""

    def __lt__(self, other: object) -> bool:
        """Always true, so the result identifies which method ran."""
        return True


class ComparingContext(Context):
    """One participant, one role, bound on the class."""

    roles: ClassVar[dict[str, type]] = {'amount': ComparableAmount}

    def __init__(self, amount: Money) -> None:
        self.amount = amount


class ComparingInstanceContext(InstanceContext):
    """The same, bound on the instance."""

    roles: ClassVar[dict[str, type]] = {'amount': ComparableAmount}

    def __init__(self, amount: Money) -> None:
        self.amount = amount


COMPARING: dict[str, AmountBinder] = {'class': ComparingContext, 'instance': ComparingInstanceContext}


@pytest.fixture
def accounts() -> dict[str, Any]:
    """The participants, by holder name."""
    return {}


@pytest.fixture
def running() -> dict[str, Any]:
    """State passed from the `When` steps to the `Then` steps."""
    return {'context': None, 'error': None, 'blob': None, 'failures': [], 'amount': None}


@pytest.fixture(autouse=True)
def close_anything_left_open(running: dict) -> Iterator[None]:
    """Close any context the scenario left open.

    Several scenarios open a context in a `When` step and inspect the
    participant from a `Then` step, so the exit cannot live in the `When`. If
    one of those assertions fails, the context remains installed in the
    `ContextVar` and the next scenario calling `context()` receives it, which
    is the failure `_release` exists to prevent. This keeps one failing
    scenario from causing others to fail.
    """
    yield
    opened = running.get('context')
    if opened is not None and opened._active:  # noqa: SLF001 -- reading the flag this net is about
        opened.__exit__()


@given(parsers.parse('an account "{holder}" with {amount:d} {currency}'))
def an_account(accounts: dict, holder: str, amount: int, currency: str) -> None:
    """A plain domain object, which is the only kind all four binders accept."""
    accounts[holder] = Account(holder, Money(amount, currency))


@given(parsers.parse('a shared account with {amount:d} {currency}'))
def a_shared_account(accounts: dict, amount: int, currency: str) -> None:
    """The account two concurrent requests both want."""
    accounts['shared'] = Account('Erin', Money(amount, currency))


@given('a source that cannot play a role')
def a_source_that_cannot(accounts: dict) -> None:
    """Slotted, so binding fails after other participants are already bound."""
    accounts['Alice'] = SlottedAccount('Alice', Money(1000))


# ---------------------------------------------------------------------------
# Opening a transfer and looking at the participant while it is open
# ---------------------------------------------------------------------------


@when(parsers.parse('a transfer is opened with the {binder} binder'))
def open_a_transfer(accounts: dict, running: dict, binder: str) -> None:
    """Enter the context and leave it open, so the `Then` steps see it bound."""
    opened = BINDERS[binder](accounts['Alice'], accounts['Bob'], Money(10))
    opened.__enter__()
    running['context'] = opened


@when(parsers.parse('the same context is entered a second time'))
def enter_again(running: dict) -> None:
    """A running use case is not a nesting construct."""
    try:
        running['context'].__enter__()
    except RuntimeError as exc:
        running['error'] = exc


@when(parsers.parse('"{holder}" is pickled'))
def is_pickled(accounts: dict, running: dict, holder: str) -> None:
    """Serializing a participant mid-use-case is a defect; the question is when it is reported."""
    try:
        running['blob'] = pickle.dumps(accounts[holder])
    except Exception as exc:  # noqa: BLE001 -- which exception is the Then's business
        running['error'] = exc


@then(parsers.parse('the type of "{holder}" reports itself as "{name}"'))
def type_reports_itself_as(accounts: dict, holder: str, name: str) -> None:
    """What a debugger shows while the role is on."""
    assert type(accounts[holder]).__name__ == name


@then(parsers.parse('asking "{holder}" for an undefined attribute blames "{name}"'))
def attribute_error_blames(accounts: dict, running: dict, holder: str, name: str) -> None:
    """The message CPython builds from the type name.

    CPython builds this message out of the type's `tp_name`, which follows
    `__name__` -- which is why renaming the class works here and a metaclass
    would not.
    """
    missing = 'no_such_attribute'
    with pytest.raises(AttributeError) as caught:
        getattr(accounts[holder], missing)

    assert f"'{name}' object has no attribute" in str(caught.value)
    running['context'].__exit__()


@then('it is refused as not re-entrant')
def refused_as_not_re_entrant(running: dict) -> None:
    """And it says so, instead of failing three frames away on a spent token."""
    assert isinstance(running['error'], RuntimeError)
    assert 'not re-entrant' in str(running['error'])
    running['context'].__exit__()


@then('it is refused as it is written')
def refused_as_written(running: dict) -> None:
    """`dumps` raises on the spot: the class is in no module, so pickle cannot name it."""
    assert isinstance(running['error'], pickle.PicklingError)
    assert running['blob'] is None
    running['context'].__exit__()


@then('it is written and fails on the read')
def written_and_fails_on_read(running: dict) -> None:
    """The worse failure: it moves out of the process that made the mistake.

    A bound method pickles as "call `getattr` on this object with this name",
    so `dumps` succeeds and the bytes cannot be loaded -- at load time the
    reconstructed account has no `transfer` for `getattr` to find.
    """
    assert running['error'] is None
    assert running['blob'] is not None
    running['context'].__exit__()

    with pytest.raises(AttributeError, match='transfer'):
        pickle.loads(running['blob'])  # noqa: S301 -- our own bytes, this test's own process


# ---------------------------------------------------------------------------
# Two threads over one account
# ---------------------------------------------------------------------------


@when(parsers.parse('a transfer out of it is opened with the {binder} binder'))
def open_a_transfer_out_of_the_shared_account(accounts: dict, running: dict, binder: str) -> None:
    """The first context, left open so the second one meets a participant already bound."""
    opened = BINDERS[binder](accounts['shared'], Account('Frank', Money(0)), Money(5))
    opened.__enter__()
    running['context'] = opened


@when('a second transfer out of it is opened with the same binder')
def open_a_second_transfer_out_of_the_shared_account(accounts: dict, running: dict) -> None:
    """One thread, two live contexts over one account: a defect, not contention.

    Nothing here is waiting for anything, so `SerializedContext` has nothing to
    serialize -- its `RLock` is re-entrant to the thread that already holds it,
    and the second `__enter__` walks straight through to the same collision the
    other class binders get.
    """
    second = type(running['context'])(accounts['shared'], Account('Grace', Money(0)), Money(7))
    try:
        second.__enter__()
    except Exception as exc:  # noqa: BLE001 -- the refusal is the measurement
        running['error'] = exc


@then('the second one is refused with an MRO error')
def second_refused_with_mro_error(running: dict) -> None:
    """`__class__` is state of the object, and the object is already wearing a role."""
    assert isinstance(running['error'], TypeError)
    assert 'consistent method resolution order' in str(running['error']).lower()


@then('the second one is refused as the name is taken')
def second_refused_name_taken(running: dict) -> None:
    """No class to collide over, so the refusal comes from `_bind` itself."""
    assert isinstance(running['error'], RuntimeError)
    assert 'already has' in str(running['error'])


@when(parsers.parse('two threads run overlapping transfers out of it with the {binder} binder'))
def two_overlapping_threads(accounts: dict, running: dict, binder: str) -> None:
    """One slow transfer holds its roles across a gap the fast one arrives in.

    The gap is what makes the overlap deterministic instead of hopeful: the
    slow thread signals once it is inside, and only then does the fast one go.
    """
    context_class = BINDERS[binder]
    shared = accounts['shared']
    failures: list[tuple[str, str]] = running['failures']
    inside = threading.Event()

    def slow() -> None:
        try:
            held = context_class(shared, Account('Frank', Money(0)), Money(5))
            with held:
                inside.set()
                time.sleep(0.3)
                held.run_script()
        except Exception as exc:  # noqa: BLE001 -- the failure is the measurement
            failures.append(('slow', type(exc).__name__))

    def fast() -> None:
        inside.wait(2)
        try:
            context_class(shared, Account('Grace', Money(0)), Money(7)).execute()
        except Exception as exc:  # noqa: BLE001 -- the failure is the measurement
            failures.append(('fast', type(exc).__name__))

    threads = [threading.Thread(target=slow), threading.Thread(target=fast)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)


@then('the thread that arrived second fails')
def second_thread_fails(accounts: dict, running: dict) -> None:
    """Loud, immediate, and at the scene of the crime -- only the slow transfer lands."""
    assert running['failures'] == [('fast', 'TypeError')]
    assert accounts['shared'].balance == Money(1_000_000 - 5)


@then('both transfers complete')
def both_transfers_complete(accounts: dict, running: dict) -> None:
    """The second waits for the first instead of finding the slot taken."""
    assert running['failures'] == []
    assert accounts['shared'].balance == Money(1_000_000 - 5 - 7)


@then('the thread that arrived second is refused')
def second_thread_is_refused(accounts: dict, running: dict) -> None:
    """Turned away at bind time rather than writing over the roles already there.

    The same shape as the class binders, by a different route and with a
    different exception: `_bind` will not overwrite a name the object already
    has. What it buys is that the transfer already running is left alone and
    completes, rather than losing its methods to the other context's exit.
    """
    assert running['failures'] == [('fast', 'RuntimeError')]
    assert accounts['shared'].balance == Money(1_000_000 - 5)


@when(parsers.parse('two threads run a transfer out of it and a transfer into it with the {binder} binder'))
def two_threads_wanting_different_roles(accounts: dict, running: dict, binder: str) -> None:
    """The overlap that raises nothing: one thread wants `SourceAccount`, the other `DestinationAccount`.

    `DestinationAccount` over `Account@SourceAccount` has a consistent MRO, so
    the class binders have nothing to refuse and the interleave is the whole
    measurement. Each thread holds its context open until the other has run its
    part, so the two leave in the order they arrived rather than nested -- which
    is what makes a class binder restore a class that still carries the other's
    role.

    Both waits are bounded, because one binder is expected not to allow the
    overlap in the first place: under `SerializedContext` the second thread is
    still waiting for the account when the first gives up waiting for it, and
    that is the property being measured rather than a hang.
    """
    context_class = BINDERS[binder]
    shared = accounts['shared']
    failures: list[tuple[str, str]] = running['failures']
    paying_out_inside = threading.Event()
    paid_into_ran = threading.Event()
    paying_out_left = threading.Event()

    def paying_out() -> None:
        try:
            held = context_class(shared, Account('Frank', Money(0)), Money(5))
            with held:
                paying_out_inside.set()
                paid_into_ran.wait(1)
                held.run_script()
        except Exception as exc:  # noqa: BLE001 -- whatever escapes is the measurement
            failures.append(('out', type(exc).__name__))
        finally:
            paying_out_left.set()

    def paid_into() -> None:
        paying_out_inside.wait(2)
        try:
            held = context_class(Account('Grace', Money(1000)), shared, Money(7))
            with held:
                held.run_script()
                paid_into_ran.set()
                paying_out_left.wait(1)
        except Exception as exc:  # noqa: BLE001 -- whatever escapes is the measurement
            failures.append(('in', type(exc).__name__))

    threads = [threading.Thread(target=paying_out), threading.Thread(target=paid_into)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)


@then('the account is left playing a role for good')
def account_left_playing_a_role(accounts: dict, running: dict) -> None:
    """Both transfers land, and the account never gets itself back.

    The context that leaves last restores the class it found on the way in,
    which by then already carried the other context's role. Nothing raises at
    any point, the balances are right, and the account is left holding
    `transfer` outside every context -- where the next transfer out of it will
    stack `SourceAccount` on itself and finally produce the MRO error, in a
    request that did nothing wrong.
    """
    assert running['failures'] == []
    assert accounts['shared'].balance == Money(1_000_000 - 5 + 7)
    assert hasattr(accounts['shared'], 'transfer')


@then('the account is itself again')
def account_is_itself_again(accounts: dict, running: dict) -> None:
    """Both transfers land and the account comes out of them holding nothing."""
    assert running['failures'] == []
    assert accounts['shared'].balance == Money(1_000_000 - 5 + 7)
    assert not hasattr(accounts['shared'], 'transfer')
    assert type(accounts['shared']) is Account


# ---------------------------------------------------------------------------
# A role contributing a dunder
# ---------------------------------------------------------------------------


@when(parsers.parse('a role defining __lt__ is lent to an amount with the {binder} binder'))
def lend_a_dunder(running: dict, binder: str) -> None:
    """The role wants to make its player comparable, which only one binder allows."""
    amount = Money(5)
    running['amount'] = amount
    running['context'] = COMPARING[binder](amount)
    running['context'].__enter__()


@then("the less-than operator on the amount runs the role's method")
def operator_runs_the_role(running: dict) -> None:
    """The synthesized class is a real class, so the operator finds the role's method."""
    assert (running['amount'] < Money(1)) is True
    running['context'].__exit__()


@then('the less-than operator on the amount ignores the role')
def operator_ignores_the_role(running: dict) -> None:
    """The role's `__lt__` never arrives, and would do nothing if it did.

    `InstanceContext` skips dunders when it binds, and the reason is the second
    half of this assertion: special methods are resolved on the *type*, so a
    `__lt__` sitting in an instance's `__dict__` is invisible to `<`. Rather
    than lend a method that could never run, the binder declines to lend it --
    so what the amount still has is `Money`'s own, and `Money(5) < Money(1)` is
    False. `tests/unit/test_instance_roles.py` shows the other half: written in
    by hand, it answers when called by name and the operator walks past it.
    """
    amount = running['amount']
    assert isinstance(amount.__lt__, types.MethodType)
    assert amount.__lt__.__qualname__.startswith('Money.'), 'the role should not have been lent at all'
    assert amount.__lt__(Money(1)) is False
    assert (amount < Money(1)) is False
    running['context'].__exit__()


# ---------------------------------------------------------------------------
# All-or-nothing binding
# ---------------------------------------------------------------------------


@when(parsers.parse('a transfer out of it is attempted with the {binder} binder'))
def attempt_doomed_transfer(accounts: dict, running: dict, binder: str) -> None:
    """The source refuses, after the other two participants may already be bound."""
    running['destination'] = accounts['Bob']
    running['amount'] = Money(250)
    try:
        BINDERS[binder](accounts['Alice'], running['destination'], running['amount']).execute()
    except Exception as exc:  # noqa: BLE001 -- which exception is the Then's business
        running['error'] = exc


@then('the transfer is refused')
def the_transfer_is_refused(running: dict) -> None:
    """It failed, which is the premise rather than the finding."""
    assert running['error'] is not None


@then('no participant is left holding a role')
def no_participant_left_holding(running: dict) -> None:
    """Whatever bound before the refusal was undone."""
    assert not hasattr(running['destination'], 'receive')
    assert not hasattr(running['amount'], 'withdraw_from')


@then('no context is left running')
def no_context_left_running() -> None:
    """The one that would poison the thread if it were skipped.

    A context that failed half way and stayed installed would be handed to the
    next role that asked `context()` for its peers -- silently, and for the
    rest of the thread's life.
    """
    with pytest.raises(LookupError):
        context()
