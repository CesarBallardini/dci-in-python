"""Can a *persisted* domain object play a role? It depends entirely on the mapping.

An integration test rather than a unit test, deliberately: the question only
has meaning after a real round trip through a real database. Define the
mapping, write a row, load it back in a fresh session, and only then give the
loaded object a part to play, which is the point at which a real system would
do so.

The answer depends entirely on the mapping style:

* **Declarative mapping** -- `class Account(Base)`, the common form -- **fails
  under class binding.** `DeclarativeBase` contributes `__slots__ = ()`, and
  mixing a plain role class over that produces an instance layout CPython
  refuses to reassign. The same `object layout differs` limit as a
  hand-written `__slots__`, reached without anyone selecting slots.
* **Imperative mapping** -- the domain class stays plain Python and the table
  is described separately -- **works completely.** The object loads, plays its
  part, is mutated through the role, gives the role back, and the change
  reaches the database.

This turns a limitation into an architectural constraint, and a familiar one:
class binding works only if domain objects are plain Python objects with no
knowledge of the infrastructure. That is what DCI asks for in any case -- Data
is meant to be barely smart data -- and what DDD and Clean Architecture ask
for on independent grounds. The mechanism does not penalise persistence; it
penalises letting the persistence framework into the domain class.

Note what is mapped below: `banking.data.account.Account` itself, unmodified.
Nothing was added to the domain to make this work; all the adaptation happens
in `MoneyType`, on the infrastructure side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from pydantic import BaseModel
from sqlalchemy import Column, String, Table, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, clear_mappers, mapped_column, registry
from sqlalchemy.types import TypeDecorator

from banking.contexts.money_transfer import InstanceMoneyTransferContext, MoneyTransferContext
from banking.data.account import Account
from banking.data.money import Money

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.engine import Dialect, Engine

    from banking.data.account import AccountLike


class MoneyType(TypeDecorator):
    """Infrastructure: how a `Money` becomes a column, and back.

    Defined here and not in `banking.data.money` because the value
    object never learns that a database exists.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Money | None, dialect: Dialect) -> str | None:
        """Money -> column."""
        return None if value is None else f'{value.amount}:{value.currency}'

    def process_result_value(self, value: str | None, dialect: Dialect) -> Money | None:
        """Column -> Money."""
        if value is None:
            return None
        amount, currency = value.split(':')
        return Money(int(amount), currency)


class ContrastBase(DeclarativeBase):
    """Base for the mapping style that does not work, kept for the contrast."""


class DeclarativeAccount(ContrastBase):
    """An account mapped the way SQLAlchemy's own docs would have you map it."""

    __tablename__ = 'declarative_accounts'

    holder: Mapped[str] = mapped_column(primary_key=True)
    balance: Mapped[Money] = mapped_column(MoneyType)

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


class PydanticAccount(BaseModel):
    """The same account as a pydantic model, for a second contrast."""

    holder: str
    balance: Money

    model_config = {'arbitrary_types_allowed': True}

    def debit(self, amount: Money) -> None:
        self.balance = self.balance - amount

    def credit(self, amount: Money) -> None:
        self.balance = self.balance + amount


@pytest.fixture(scope='module')
def mapped_domain() -> Iterator[registry]:
    """Map the real `Account` imperatively, and undo it afterwards.

    `map_imperatively` instruments the class globally, so the teardown matters:
    without `clear_mappers()` every later test in this worker would be handling
    an instrumented `Account`.
    """
    mapper_registry = registry()
    accounts = Table(
        'accounts',
        mapper_registry.metadata,
        Column('holder', String, primary_key=True),
        Column('balance', MoneyType, nullable=False),
    )
    mapper_registry.map_imperatively(Account, accounts)
    yield mapper_registry
    clear_mappers()


@pytest.fixture
def engine(mapped_domain: registry, tmp_path: Path) -> Engine:
    """A real SQLite file -- not in-memory, so the round trip is a real one."""
    engine = create_engine(f'sqlite:///{tmp_path / "bank.db"}')
    mapped_domain.metadata.create_all(engine)
    ContrastBase.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account('Alice', Money(1000)))
        session.add(Account('Bob', Money(0)))
        session.commit()
    return engine


@pytest.mark.integration
def test_an_imperatively_mapped_entity_plays_its_role(engine: Engine) -> None:
    """The real `Account`, loaded from disk, runs the whole use case."""
    with Session(engine) as session:
        alice = session.get(Account, 'Alice')
        bob = session.get(Account, 'Bob')
        assert alice is not None and bob is not None

        MoneyTransferContext(alice, bob, Money(250)).execute()

        assert (alice.balance, bob.balance) == (Money(750), Money(250))


@pytest.mark.integration
def test_the_transfer_survives_the_round_trip(engine: Engine) -> None:
    """And it is really persisted -- committed, and read back in a new session."""
    with Session(engine) as session:
        alice = session.get(Account, 'Alice')
        bob = session.get(Account, 'Bob')
        assert alice is not None and bob is not None
        MoneyTransferContext(alice, bob, Money(250)).execute()
        session.commit()

    with Session(engine) as session:
        reloaded_alice = session.get(Account, 'Alice')
        reloaded_bob = session.get(Account, 'Bob')
        assert reloaded_alice is not None and reloaded_bob is not None
        assert (reloaded_alice.balance, reloaded_bob.balance) == (Money(750), Money(250))


@pytest.mark.integration
def test_the_role_is_released_and_the_class_is_the_mapped_one_again(engine: Engine) -> None:
    """Leaving the context gives SQLAlchemy back the class it instrumented."""
    with Session(engine) as session:
        alice = session.get(Account, 'Alice')
        bob = session.get(Account, 'Bob')
        assert alice is not None and bob is not None

        with MoneyTransferContext(alice, bob, Money(10)):
            assert type(alice).__name__ == 'Account@SourceAccount'

        assert type(alice) is Account


@pytest.mark.integration
def test_a_declaratively_mapped_entity_cannot_play_a_role(engine: Engine) -> None:
    """The contrast, and the reason the mapping style is an architectural choice."""
    with Session(engine) as session:
        session.add(DeclarativeAccount(holder='Charlie', balance=Money(1000)))
        session.add(DeclarativeAccount(holder='Dave', balance=Money(0)))
        session.commit()

    with Session(engine) as session:
        charlie = session.get(DeclarativeAccount, 'Charlie')
        dave = session.get(DeclarativeAccount, 'Dave')
        assert charlie is not None and dave is not None

        # `cast`, and not a suppressed diagnostic: a declaratively mapped class
        # declares `Mapped[str]` where the instance really holds a `str`, so
        # the checker cannot see that this satisfies `AccountLike` even though
        # at runtime it does. Which is the whole setup for the failure below --
        # the protocol is not what stops it.
        with pytest.raises(TypeError, match='object layout differs'):
            MoneyTransferContext(cast('AccountLike', charlie), cast('AccountLike', dave), Money(250)).execute()


@pytest.mark.integration
def test_the_other_binder_rescues_the_declarative_entity(engine: Engine) -> None:
    """And the mapping style stops being the only way in, at a price.

    `InstanceContext` never touches `__class__`, so the layout that stops
    `Context` dead is irrelevant to it: the entity everyone actually writes --
    `class Account(Base)` -- plays its part, and the change reaches the
    database like any other attribute change.

    This narrows the finding above rather than contradicting it. What the
    imperative mapping provides is DCI with *class* binding, and with it the
    two things instance binding cannot do: roles that contribute special
    methods, and an immediate failure when two contexts collide rather than a
    silent one. The architectural argument for keeping the
    framework out of the domain class survives -- it just stops being the only
    way to get a persisted object into a role.
    """
    with Session(engine) as session:
        session.add(DeclarativeAccount(holder='Erin', balance=Money(1000)))
        session.add(DeclarativeAccount(holder='Frank', balance=Money(0)))
        session.commit()

    with Session(engine) as session:
        erin = session.get(DeclarativeAccount, 'Erin')
        frank = session.get(DeclarativeAccount, 'Frank')
        assert erin is not None and frank is not None

        InstanceMoneyTransferContext(cast('AccountLike', erin), cast('AccountLike', frank), Money(250)).execute()

        assert (erin.balance, frank.balance) == (Money(750), Money(250))
        # The role came back off, and SQLAlchemy never saw a class it had not
        # instrumented -- because there never was one.
        assert not hasattr(erin, 'transfer')
        assert type(erin) is DeclarativeAccount
        session.commit()

    with Session(engine) as session:
        reloaded = session.get(DeclarativeAccount, 'Erin')
        assert reloaded is not None
        assert reloaded.balance == Money(750)


@pytest.mark.integration
def test_a_pydantic_model_can_play_a_role() -> None:
    """Not a story about ORMs: it is a story about who owns your class layout."""
    alice = PydanticAccount(holder='Alice', balance=Money(1000))
    bob = PydanticAccount(holder='Bob', balance=Money(0))

    MoneyTransferContext(alice, bob, Money(250)).execute()

    assert (alice.balance, bob.balance) == (Money(750), Money(250))


# ---------------------------------------------------------------------------
# The two cells the README's table would otherwise be asserting on trust
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_the_other_binder_also_takes_the_styles_that_already_worked(engine: Engine) -> None:
    """`InstanceContext` adds rows to the table without losing the ones there.

    The two above are the cases class binding already handles, so it would be
    easy to assume instance binding handles them too and never check. The
    README prints a column of five answers for each binder; this is what stops
    two of the ten from being a guess.
    """
    alice = PydanticAccount(holder='Alice', balance=Money(1000))
    bob = PydanticAccount(holder='Bob', balance=Money(0))
    InstanceMoneyTransferContext(alice, bob, Money(250)).execute()
    assert (alice.balance, bob.balance) == (Money(750), Money(250))

    with Session(engine) as session:
        mapped_alice = session.get(Account, 'Alice')
        mapped_bob = session.get(Account, 'Bob')
        assert mapped_alice is not None and mapped_bob is not None

        InstanceMoneyTransferContext(mapped_alice, mapped_bob, Money(250)).execute()

        assert (mapped_alice.balance, mapped_bob.balance) == (Money(750), Money(250))
        assert not hasattr(mapped_alice, 'transfer')
