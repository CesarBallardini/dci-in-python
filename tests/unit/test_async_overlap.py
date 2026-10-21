"""The overlap without threads: two asyncio tasks, one event loop, one thread.

`test_limits.py` and `test_serialized_roles.py` provoke the overlap with two
threads. What they measure is not a property of threads: it is one object in
memory inside two live contexts at once. Two tasks suspended at an `await`
inside their contexts reach the same situation on a single thread. That is how
an asynchronous server reaches it, and it is the only way to reach it in a
runtime that cannot start a thread (Pyodide, in the browser).

Each task gets its own copy of the `ContextVar` state when it is created, so
`context()` resolves per task exactly as it resolves per thread. The class of
the shared account does not: it is state of the object. Every binder therefore
behaves as it does under threads, with one exception. `SerializedContext`
holds an `RLock`, which belongs to a thread, and every task runs on the same
thread, so the second task re-enters the lock instead of waiting for it.

The tasks order themselves with `asyncio.Event`, not with sleep durations, so
the interleaving is fixed by the code and not by timing.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, NamedTuple

import pytest

from banking.contexts.money_transfer import (
    InstanceMoneyTransferContext,
    MoneyTransferContext,
    SerializedMoneyTransferContext,
    TransparentMoneyTransferContext,
)
from banking.data.account import Account
from banking.data.money import Money

if TYPE_CHECKING:
    from typing import Protocol, Self

    from banking.data.account import AccountLike

    class RunningUseCase(Protocol):
        """What a scenario needs from a context: open it, run the script, close it."""

        def __enter__(self) -> Self:
            """Bind the roles."""
            ...

        def __exit__(self, *exc_info: object) -> bool:
            """Unbind the roles."""
            ...

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


class TaskFailureDto(NamedTuple):
    """A task that was turned away: which one, and the class of what it raised."""

    task: str
    exception_type: type[Exception]


@pytest.mark.unit
@pytest.mark.event_loop
@pytest.mark.parametrize(
    ('binder', 'refusal'),
    [
        pytest.param(MoneyTransferContext, TypeError, id='class'),
        pytest.param(TransparentMoneyTransferContext, TypeError, id='transparent'),
        pytest.param(SerializedMoneyTransferContext, TypeError, id='serialized'),
        pytest.param(InstanceMoneyTransferContext, RuntimeError, id='instance'),
    ],
)
def test_the_task_that_arrives_second_is_refused(binder: TransferBinder, refusal: type[Exception]) -> None:
    """Two transfers out of one account, served by two tasks.

    The slow task holds `SourceAccount` across an `await`, and the fast one
    tries to take the same role in that gap. The class binders refuse with an
    MRO error and the instance binder with its own `RuntimeError`, as they do
    under threads. The locking binder refuses as well, where under threads both
    transfers complete: the second task re-enters the lock the first holds.
    """
    shared = Account('Erin', Money(1_000_000))
    failures: list[TaskFailureDto] = []

    async def scenario() -> None:
        inside = asyncio.Event()

        async def slow() -> None:
            held = binder(shared, Account('Frank', Money(0)), Money(5))
            with held:
                inside.set()
                await asyncio.sleep(0)  # the other task opens its context in this gap
                held.run_script()

        async def fast() -> None:
            await inside.wait()
            try:
                binder(shared, Account('Grace', Money(0)), Money(7)).execute()
            except (TypeError, RuntimeError) as exc:
                failures.append(TaskFailureDto('fast', type(exc)))

        await asyncio.gather(slow(), fast())

    asyncio.run(scenario())

    assert failures == [('fast', refusal)]
    assert shared.balance == Money(1_000_000 - 5)


@pytest.mark.unit
@pytest.mark.event_loop
@pytest.mark.parametrize(
    ('binder', 'leaks'),
    [
        pytest.param(MoneyTransferContext, True, id='class'),
        pytest.param(TransparentMoneyTransferContext, True, id='transparent'),
        pytest.param(SerializedMoneyTransferContext, True, id='serialized'),
        pytest.param(InstanceMoneyTransferContext, False, id='instance'),
    ],
)
def test_a_transfer_out_and_a_transfer_in_overlap_on_one_account(binder: TransferBinder, leaks: bool) -> None:
    """The overlap that raises nothing, served by two tasks.

    One task wants the shared account as `SourceAccount`, the other as
    `DestinationAccount`. The two roles stack, both transfers land, and the two
    contexts leave in the order they arrived rather than nested, so a class
    binder's last exit restores a class that still carries the other role. The
    instance binder takes back only the names it wrote and leaves the account
    as it found it. The locking binder leaks like `Context`, where under
    threads it keeps the two transfers from overlapping at all.
    """
    shared = Account('Erin', Money(1_000_000))

    async def scenario() -> None:
        paying_out_inside = asyncio.Event()
        paid_into_ran = asyncio.Event()

        async def paying_out() -> None:
            held = binder(shared, Account('Frank', Money(0)), Money(5))
            with held:
                paying_out_inside.set()
                await paid_into_ran.wait()
                held.run_script()

        async def paid_into() -> None:
            await paying_out_inside.wait()
            held = binder(Account('Grace', Money(1000)), shared, Money(7))
            with held:
                held.run_script()
                paid_into_ran.set()
                await asyncio.sleep(0)  # the other transfer runs and leaves inside this gap

        await asyncio.gather(paying_out(), paid_into())

    asyncio.run(scenario())

    assert shared.balance == Money(1_000_000 - 5 + 7)
    assert hasattr(shared, 'transfer') is leaks


@pytest.mark.unit
@pytest.mark.event_loop
def test_serialized_does_not_serialize_asyncio_tasks() -> None:
    """Asserted deliberately: `SerializedContext` serializes threads, not tasks.

    Its lock is an `RLock`, owned by a thread, and every task on an event loop
    runs on the same thread. The second task therefore takes the lock while the
    first still holds it, and both contexts' roles are on the account at the
    same moment. Under threads the second context would wait at `__enter__`
    until the first had left. Serializing tasks requires a lock the event loop
    knows about, taken across an `await`, and none of the four binders has one.
    """
    shared = Account('Erin', Money(1_000_000))
    seen_from_inside: list[str] = []

    async def scenario() -> None:
        paying_out_inside = asyncio.Event()
        paid_into_left = asyncio.Event()

        async def paying_out() -> None:
            held = SerializedMoneyTransferContext(shared, Account('Frank', Money(0)), Money(5))
            with held:
                paying_out_inside.set()
                await paid_into_left.wait()
                held.run_script()

        async def paid_into() -> None:
            await paying_out_inside.wait()
            held = SerializedMoneyTransferContext(Account('Grace', Money(1000)), shared, Money(7))
            with held:
                seen_from_inside.append(type(shared).__name__)
                held.run_script()
            paid_into_left.set()

        await asyncio.wait_for(asyncio.gather(paying_out(), paid_into()), timeout=5)

    asyncio.run(scenario())

    assert seen_from_inside == ['Account@SourceAccount@DestinationAccount']
    assert shared.balance == Money(1_000_000 - 5 + 7)
