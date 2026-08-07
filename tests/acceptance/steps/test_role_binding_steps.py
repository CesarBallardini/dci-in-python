"""Step definitions for role_binding.feature.

Every claim the README makes about *which objects can play a role* is one row
of a table there and one example row here. The point of writing them this way
rather than as more unit tests is that the table and the feature file can be
read side by side: if a Python release changes one of these answers, the row
that changed is the one that goes red.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import attrs
import pytest
from pydantic import BaseModel
from pytest_bdd import given, parsers, scenarios, then, when
from sqlalchemy import Column, String, Table, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, registry
from sqlalchemy.types import TypeDecorator

from banking.contexts.money_transfer import InstanceMoneyTransferContext, MoneyTransferContext
from banking.data.money import Money

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.engine import Engine

    from banking.data.account import AccountLike

scenarios('../features/role_binding.feature')

BINDERS = {'class': MoneyTransferContext, 'instance': InstanceMoneyTransferContext}


# ---------------------------------------------------------------------------
# One domain object, written five ways. Only the spelling differs.
# ---------------------------------------------------------------------------


class PlainAccount:
    """The hand-written class, which is what `banking.data.Account` also is."""

    def __init__(self, holder: str, balance: Money) -> None:
        self.holder = holder
        self.balance = balance

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


@dataclass(frozen=True)
class FrozenAccount:
    """Refuses every `__setattr__`, `__class__` included."""

    holder: str
    balance: Money

    def debit(self, amount: Money) -> None:
        object.__setattr__(self, 'balance', self.balance - amount)

    def credit(self, amount: Money) -> None:
        object.__setattr__(self, 'balance', self.balance + amount)


@attrs.define
class AttrsAccount:
    """`@define` means `slots=True`, so there is no instance dictionary."""

    holder: str
    balance: Money

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


class PydanticAccount(BaseModel):
    """A validated model whose class is still an ordinary Python class."""

    holder: str
    balance: Money
    model_config = {'arbitrary_types_allowed': True}

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


STYLES: dict[str, Callable[[str, Money], Any]] = {
    'a plain class': PlainAccount,
    'a frozen dataclass': FrozenAccount,
    'an attrs class': AttrsAccount,
    'a pydantic model': lambda holder, balance: PydanticAccount(holder=holder, balance=balance),
}


# ---------------------------------------------------------------------------
# The two mappings, on classes of this file's own so the real `Account` is
# never instrumented here -- `tests/integration/test_orm_roles.py` owns that.
# ---------------------------------------------------------------------------


class MoneyType(TypeDecorator):
    """Stores a `Money` as `amount:currency`, so the domain never learns of the DB."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Money | None, dialect: object) -> str | None:
        """Money -> column."""
        return None if value is None else f'{value.amount}:{value.currency}'

    def process_result_value(self, value: str | None, dialect: object) -> Money | None:
        """Column -> Money."""
        if value is None:
            return None
        amount, currency = value.split(':')
        return Money(int(amount), currency)


class ImperativeAccount(PlainAccount):
    """Mapped by describing its table separately; the class learns nothing."""


@dataclass(frozen=True)
class MappedDomain:
    """One database and the two entity classes mapped into it, for one test."""

    engine: Engine
    imperative: type
    declarative: type


@pytest.fixture
def mapped() -> Iterator[MappedDomain]:
    """Both mappings, built per test and torn down without touching anyone else's.

    Two things here are deliberate, and both are about isolation.

    The declarative class is defined *inside* the fixture rather than at module
    level, because the teardown un-maps whatever it built: a module-level class
    would be un-mapped once and arrive at the second test having forgotten its
    columns.

    And the teardown disposes **these two registries** rather than calling
    `clear_mappers()`. That function is global: it un-instruments every mapped
    class in the process, including the module-level ones in
    `tests/integration/test_orm_roles.py`, which are mapped at import time and
    have no idea this file exists. Scoped disposal keeps the suite
    order-independent in both directions.
    """
    reg = registry()
    reg.map_imperatively(
        ImperativeAccount,
        Table(
            'imperative_accounts',
            reg.metadata,
            Column('holder', String, primary_key=True),
            Column('balance', MoneyType, nullable=False),
        ),
    )

    class Base(DeclarativeBase):
        """Contributes `__slots__ = ()`, which is what blocks class binding below."""

    class DeclarativeAccount(Base):
        """The entity almost everyone writes."""

        __tablename__ = 'declarative_accounts'
        holder: Mapped[str] = mapped_column(primary_key=True)
        balance: Mapped[Money] = mapped_column(MoneyType)

        def debit(self, amount: Money) -> None:
            """Take money out."""
            self.balance = self.balance - amount

        def credit(self, amount: Money) -> None:
            """Put money in."""
            self.balance = self.balance + amount

    made = create_engine('sqlite://')
    reg.metadata.create_all(made)
    Base.metadata.create_all(made)
    yield MappedDomain(made, ImperativeAccount, DeclarativeAccount)
    made.dispose()
    reg.dispose()
    Base.registry.dispose()


@pytest.fixture
def participants() -> dict[str, Any]:
    """The source and the destination, however they ended up being written."""
    return {}


@pytest.fixture
def outcome() -> dict[str, Exception | None]:
    """What the transfer did, so a `Then` can ask about it."""
    return {'error': None}


# ---------------------------------------------------------------------------


@given(parsers.parse('a source and a destination written as {style}'))
def written_as(participants: dict, style: str) -> None:
    """Build the pair in the style named by the example row."""
    build = STYLES[style]
    participants['source'] = build('Alice', Money(1000))
    participants['destination'] = build('Bob', Money(0))


@given(parsers.parse('a source and a destination mapped {mapping} and loaded from the database'))
def mapped_and_loaded(participants: dict, mapped: MappedDomain, mapping: str) -> None:
    """Write two rows, then load them back in a fresh session -- as a real system would.

    Loading them back is the part that makes this worth a database: a role
    lent to an object that never left memory proves nothing about persistence.
    """
    imperative = mapping == 'imperatively'
    cls = mapped.imperative if imperative else mapped.declarative

    def build(holder: str, balance: Money) -> object:
        return cls(holder, balance) if imperative else cls(holder=holder, balance=balance)

    with Session(mapped.engine) as session:
        session.add(build('Alice', Money(1000)))
        session.add(build('Bob', Money(0)))
        session.commit()

    session = Session(mapped.engine)
    participants['session'] = session
    participants['source'] = session.get(cls, 'Alice')
    participants['destination'] = session.get(cls, 'Bob')


@when(parsers.parse('they run a transfer of {amount:d} with the role bound on the {binding}'))
def run_transfer(participants: dict, outcome: dict, amount: int, binding: str) -> None:
    """Run the one use case, lent out by the binder the example row names."""
    context = BINDERS[binding]
    source: AccountLike = participants['source']
    destination: AccountLike = participants['destination']
    try:
        context(source, destination, Money(amount)).execute()
    except Exception as exc:  # noqa: BLE001 -- which exception is the Then's business
        outcome['error'] = exc


@then('the transfer succeeds')
def transfer_succeeds(participants: dict, outcome: dict) -> None:
    """No refusal, and the money actually moved."""
    assert outcome['error'] is None, f'refused with {outcome["error"]!r}'
    assert participants['source'].balance == Money(750)
    assert participants['destination'].balance == Money(250)


@then('the transfer is refused')
def transfer_is_refused(participants: dict, outcome: dict) -> None:
    """The mechanism said no, and nothing moved."""
    assert outcome['error'] is not None, 'expected a refusal, the transfer went through'
    assert participants['source'].balance == Money(1000)
    assert participants['destination'].balance == Money(0)


@then(parsers.parse('reloading them in a new session shows {source_left:d} and {destination_left:d}'))
def reloading_shows(participants: dict, mapped: MappedDomain, source_left: int, destination_left: int) -> None:
    """The role mutated a real row, not a copy in memory."""
    participants['session'].commit()
    participants['session'].close()

    with Session(mapped.engine) as session:
        source = session.get(mapped.imperative, 'Alice')
        destination = session.get(mapped.imperative, 'Bob')
        assert source is not None and destination is not None
        assert source.balance == Money(source_left)
        assert destination.balance == Money(destination_left)
