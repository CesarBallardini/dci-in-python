"""Whether locking the participants resolves the collision, measured.

`test_limits.py` shows two live contexts over one account failing with an MRO
error. That failure is unavoidable *while both contexts hold the object at the
same time*, which is a narrower statement. `SerializedContext` prevents them
from holding it at the same time, and these tests check the four properties
that must hold before that counts as a solution:

1. the collision does not occur under real threads;
2. the balances are correct afterwards, including under the lost update that
   was always possible and is unrelated to DCI;
3. transfers that share no participant still run in parallel, so this is not
   a global lock;
4. transfers in opposite directions between the same two accounts do not
   deadlock;
5. the overlap that raises *no* error -- two contexts wanting different roles
   of the same account, which leaves the role bound for good -- is closed as
   well, up to the one boundary a lock cannot cover.
"""

from __future__ import annotations

import threading
import time

import pytest

from banking.contexts.money_transfer import MoneyTransferContext, SerializedMoneyTransferContext
from banking.data.account import Account
from banking.data.money import Money


def run_all(targets: list[threading.Thread], timeout: float = 10.0) -> None:
    """Start every thread, join them all, and insist none is still running."""
    for thread in targets:
        thread.start()
    for thread in targets:
        thread.join(timeout)
    assert not any(thread.is_alive() for thread in targets), 'a thread did not finish -- suspect a deadlock'


def transferring(source: Account, destination: Account, amount: int) -> threading.Thread:
    """A thread that runs one serialized transfer, ready to start."""
    return threading.Thread(target=SerializedMoneyTransferContext(source, destination, Money(amount)).execute)


@pytest.mark.unit
def test_the_collision_is_gone_under_threads() -> None:
    """The scenario `test_limits.py` fails on, run against the locking binder.

    Same shape: one shared account, two concurrent transfers out of it. With
    `MoneyTransferContext` the second one dies of an MRO error. Here the second
    one waits, and both go through.
    """
    shared = Account('Erin', Money(1000))
    frank = Account('Frank', Money(0))
    grace = Account('Grace', Money(0))
    failures: list[str] = []

    def transfer(destination: Account, amount: int) -> None:
        try:
            SerializedMoneyTransferContext(shared, destination, Money(amount)).execute()
        except Exception as exc:  # noqa: BLE001 -- the test is about what escapes
            failures.append(type(exc).__name__)

    run_all(
        [
            threading.Thread(target=transfer, args=(frank, 10)),
            threading.Thread(target=transfer, args=(grace, 20)),
        ]
    )

    assert failures == []
    assert (frank.balance, grace.balance) == (Money(10), Money(20))
    assert shared.balance == Money(970)


@pytest.mark.unit
def test_it_also_closes_the_lost_update_that_was_never_about_dci() -> None:
    """The race underneath the race, and the reason the lock is not a DCI tax.

    `balance = balance - amount` is a read, a subtract and a write. Twenty
    threads doing that to one account will lose updates whichever way roles are
    bound -- this is the plainest shared-mutable-state bug there is. Holding the
    participants for the length of the use case fixes the binding collision and
    this at the same time, because they are the same lock.
    """
    shared = Account('Erin', Money(1000))
    destinations = [Account(f'D{index}', Money(0)) for index in range(20)]

    run_all([transferring(shared, destination, 10) for destination in destinations])

    assert shared.balance == Money(1000 - 20 * 10)
    assert all(destination.balance == Money(10) for destination in destinations)


@pytest.mark.unit
def test_transfers_that_share_nothing_still_run_in_parallel() -> None:
    """It locks participants, not the world.

    Four transfers between eight distinct accounts, each deliberately slow.
    If the binder serialized everything, the wall clock would show it.
    """
    delay = 0.2
    pairs = [(Account(f'S{index}', Money(1000)), Account(f'D{index}', Money(0))) for index in range(4)]

    class SlowSource(Account):
        def debit(self, amount: Money) -> None:
            time.sleep(delay)
            super().debit(amount)

    slow_pairs = [(SlowSource(source.holder, source.balance), destination) for source, destination in pairs]

    started = time.perf_counter()
    run_all([transferring(source, destination, 1) for source, destination in slow_pairs])
    elapsed = time.perf_counter() - started

    # Serialized would be 4 * delay. Parallel is about one delay; allow plenty
    # of slack for a loaded CI box while still failing if they queued up.
    assert elapsed < delay * 3, f'took {elapsed:.2f}s -- looks serialized'
    assert all(destination.balance == Money(1) for _, destination in slow_pairs)


@pytest.mark.unit
def test_opposite_directions_do_not_deadlock() -> None:
    """The bug the fixed lock order exists to rule out.

    Erin pays Frank while Frank pays Erin. Locking in the order the accounts
    happen to appear in each context would have each thread holding what the
    other needs. Sorting by identity means both threads always ask in the same
    order, so one of them simply waits.
    """
    erin = Account('Erin', Money(1000))
    frank = Account('Frank', Money(1000))
    failures: list[str] = []

    def transfer(source: Account, destination: Account) -> None:
        try:
            for _ in range(50):
                SerializedMoneyTransferContext(source, destination, Money(1)).execute()
        except Exception as exc:  # noqa: BLE001
            failures.append(type(exc).__name__)

    run_all(
        [
            threading.Thread(target=transfer, args=(erin, frank)),
            threading.Thread(target=transfer, args=(frank, erin)),
        ]
    )

    assert failures == []
    assert erin.balance + frank.balance == Money(2000)


@pytest.mark.unit
def test_it_also_closes_the_overlap_that_reports_no_error_at_all() -> None:
    """The leak of `test_limits.py`, run against the locking binder.

    One account paying out while another transfer pays into it is the case the
    MRO error does not catch: `DestinationAccount` stacks over
    `Account@SourceAccount` without complaint, and whichever context leaves
    last puts back a class that still carries the other's role. Unlocked, the
    account ends the pair of transfers permanently playing `SourceAccount` and
    nothing raises to say so.

    Both accounts are deliberately slow, so the two transfers hold their
    participants long enough that an unlocked run would overlap on nearly every
    round rather than only occasionally.
    """
    rounds = 20
    failures: list[str] = []

    class SlowAccount(Account):
        """Slow enough on both sides that two transfers touching it must overlap."""

        def debit(self, amount: Money) -> None:
            time.sleep(0.01)
            super().debit(amount)

        def credit(self, amount: Money) -> None:
            time.sleep(0.01)
            super().credit(amount)

    shared = SlowAccount('Erin', Money(1000))
    frank = Account('Frank', Money(0))
    grace = SlowAccount('Grace', Money(1000))

    def transfer(source: Account, destination: Account) -> None:
        try:
            for _ in range(rounds):
                SerializedMoneyTransferContext(source, destination, Money(1)).execute()
        except Exception as exc:  # noqa: BLE001 -- the test is about what escapes
            failures.append(type(exc).__name__)

    run_all(
        [
            threading.Thread(target=transfer, args=(shared, frank)),
            threading.Thread(target=transfer, args=(grace, shared)),
        ]
    )

    assert failures == []
    # The account is itself again, which is the assertion the unlocked version
    # of this scenario fails without raising anything.
    assert type(shared) is SlowAccount
    assert not hasattr(shared, 'transfer')
    assert (shared.balance, frank.balance, grace.balance) == (Money(1000), Money(rounds), Money(1000 - rounds))


@pytest.mark.unit
def test_one_thread_reaches_the_leak_through_the_locking_binder_too() -> None:
    """The boundary of what the lock covers, and it is wider than the MRO error.

    The `RLock` is re-entrant to whoever holds it, so a single thread opening
    two contexts over one account is never made to wait. When both contexts
    want the same role that is harmless, because the MRO error arrives before
    anything is changed -- the case the table records. When they want different
    roles nothing refuses, and one thread reaches the leak through the locking
    binder exactly as it does through `Context`.

    The lock serializes *threads*. It is not a claim about one thread holding
    two live contexts over one object, which remains a defect in the calling
    code, and this is the shape that defect takes when it goes unreported.

    The scenario runs on a thread of its own so that the finished context it
    leaves installed cannot reach the rest of the suite.
    """
    shared = Account('Erin', Money(1000))
    leftover: list[str] = []

    def scenario() -> None:
        paying_out = SerializedMoneyTransferContext(shared, Account('Frank', Money(0)), Money(10))
        paid_into = SerializedMoneyTransferContext(Account('Grace', Money(500)), shared, Money(20))
        paying_out.__enter__()
        paid_into.__enter__()
        paying_out.__exit__()
        paid_into.__exit__()
        leftover.append(type(shared).__name__)

    run_all([threading.Thread(target=scenario)])

    assert leftover == ['Account@SourceAccount']


@pytest.mark.unit
def test_the_unlocked_binder_still_fails_the_same_scenario() -> None:
    """The control. Without the lock, the first test's scenario still breaks.

    Kept next to the fix so the comparison is one file apart, and so a future
    Python that changed this would fail here rather than quietly making the
    rest of this module pointless.
    """
    shared = Account('Erin', Money(1_000_000))
    first = MoneyTransferContext(shared, Account('Frank', Money(0)), Money(10))
    second = MoneyTransferContext(shared, Account('Grace', Money(0)), Money(20))

    first.__enter__()
    try:
        with pytest.raises(TypeError, match=r'[Cc]onsistent method resolution\s+order'):
            second.__enter__()
    finally:
        first.__exit__()


@pytest.mark.unit
def test_a_participant_that_dies_does_not_leak_its_lock(alice: Account, bob: Account) -> None:
    """The registry is keyed by `id()`, so it has to let go when the object does."""
    from banking.dci.serialized import _lock_registry  # noqa: PLC0415 -- reading the state under test

    SerializedMoneyTransferContext(alice, bob, Money(10)).execute()
    before = len(_lock_registry)

    doomed_source = Account('Temp', Money(100))
    doomed_destination = Account('Temp2', Money(0))
    SerializedMoneyTransferContext(doomed_source, doomed_destination, Money(1)).execute()
    assert len(_lock_registry) > before

    del doomed_source, doomed_destination

    assert len(_lock_registry) <= before + 1  # the amount object may still be alive
