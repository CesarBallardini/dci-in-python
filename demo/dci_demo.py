"""Every example in the documentation, runnable against `banking` itself.

    make demo

Sections 1 to 7 use only the standard library, which is all the DCI mechanism
requires. Section 8 compares five ways of writing the domain object and does
use SQLAlchemy, pydantic and attrs. Those are in the `dev` dependency group,
and if one is not installed that line is skipped rather than failing.

The output of this script is quoted in the blog post, so changing what it
prints means the post has to be updated from a fresh run.
"""

import threading
import time
from dataclasses import dataclass

from banking.alternatives import SourceWrapper, WrappedTransfer
from banking.contexts.money_transfer import MoneyTransferContext
from banking.data.account import Account
from banking.data.money import Money


def d(title):
    print(f'\n{"=" * 62}\n{title}\n{"=" * 62}')


d('1. The transfer works')
a = Account('Alice', Money(1000))
b = Account('Bob', Money(0))
MoneyTransferContext(a, b, Money(250)).execute()
print(a, b)

d('2. Roles are temporary')
print('before the context, does .transfer exist?', hasattr(a, 'transfer'))
amount = Money(10)
ctx = MoneyTransferContext(a, b, amount)
with ctx:
    print('inside:   type(a).__name__ =', type(a).__name__)
    print('inside:   isinstance(a, Account) =', isinstance(a, Account))
    print('inside:   does .transfer exist?', hasattr(a, 'transfer'))
    print('inside:   the amount plays a role too ->', type(amount).__name__)
print('outside:  type(a).__name__ =', type(a).__name__)
print('outside:  does .transfer exist?', hasattr(a, 'transfer'))
print('outside:  type(amount).__name__ =', type(amount).__name__)

d('3. The same object plays the opposite role in another context')
MoneyTransferContext(b, a, Money(100)).execute()
print(a, b)

d('4. Identity is preserved (this is not a wrapper)')
before = id(a)
with MoneyTransferContext(a, b, Money(1)):
    print('same id inside? ', id(a) == before)
print('same id outside?', id(a) == before)

d('5. Where class binding fails: __slots__')


class SlottedAccount:
    __slots__ = ('balance', 'holder')

    def __init__(self, holder, balance):
        self.holder, self.balance = holder, balance

    def debit(self, m):
        self.balance = self.balance - m

    def credit(self, m):
        self.balance = self.balance + m


try:
    MoneyTransferContext(SlottedAccount('Alice', Money(100)), SlottedAccount('Bob', Money(0)), Money(10)).execute()
except TypeError as e:
    print('TypeError:', e)

d('5b. The same failure, reached by the idiomatic value object')


@dataclass(frozen=True)
class FrozenAccount:
    holder: str
    balance: Money

    def debit(self, m):
        object.__setattr__(self, 'balance', self.balance - m)

    def credit(self, m):
        object.__setattr__(self, 'balance', self.balance + m)


try:
    MoneyTransferContext(FrozenAccount('Alice', Money(100)), FrozenAccount('Bob', Money(0)), Money(10)).execute()
except Exception as e:
    print(f'{type(e).__name__}: {e}')
print('the field it refuses to assign is __class__')

d('6. Where class binding fails: two live contexts over one object')
shared = Account('Erin', Money(1_000_000))
other = Account('Frank', Money(0))
third = Account('Grace', Money(0))

c1 = MoneyTransferContext(shared, other, Money(10))
c2 = MoneyTransferContext(shared, third, Money(20))
c1.__enter__()
print('with c1 open: type(shared).__name__ =', type(shared).__name__)
try:
    c2.__enter__()
except TypeError as e:
    print('c2.__enter__() ->', type(e).__name__ + ':', e)
c1.__exit__()
print('after closing c1:', type(shared).__name__)

d('6b. The same case, served by two threads')
failures = []
inside = threading.Event()


def slow_thread():
    try:
        ctx = MoneyTransferContext(shared, other, Money(5))
        with ctx:
            inside.set()
            time.sleep(0.3)  # the other thread opens its own context in this gap
            ctx.run_script()
    except Exception as e:
        failures.append(('slow', type(e).__name__, str(e)))


def fast_thread():
    inside.wait(2)
    try:
        MoneyTransferContext(shared, third, Money(7)).execute()
    except Exception as e:
        failures.append(('fast', type(e).__name__, str(e)))


t1 = threading.Thread(target=slow_thread)
t2 = threading.Thread(target=fast_thread)
t1.start()
t2.start()
t1.join(5)
t2.join(5)
for f in failures:
    print('failure:', f)
print('final balances:', shared, other, third)

d('7. The alternative without role binding: the role as a wrapper')
c = Account('Charlie', Money(500))
dd = Account('Dave', Money(0))
WrappedTransfer(c, dd, Money(50)).execute()
print(c, dd)
w = SourceWrapper(c, WrappedTransfer(c, dd, Money(0)))
print('w is c ->', w is c, '| isinstance(w, Account) ->', isinstance(w, Account))


d('8. Five ways to write the domain object, five outcomes')
# The question that decides whether DCI is usable in an existing system: the
# account was not built here, it came from a database or a model. Each case
# below is also asserted by a test, in tests/integration/test_orm_roles.py and
# tests/unit/test_limits.py.


def check(style, build_pair):
    """Build two accounts in the given style and attempt a full transfer."""
    try:
        source, destination = build_pair()
        MoneyTransferContext(source, destination, Money(250)).execute()
        print(f'  WORKS  {style:<38} -> {source.balance.amount} / {destination.balance.amount}')
    except Exception as exc:
        detail = str(exc).replace('\n', ' ')
        print(f'  BREAKS {style:<38} -> {type(exc).__name__}: {detail[:58]}')


# The two SQLAlchemy variants share MoneyType, the piece of infrastructure that
# keeps the domain from learning that a database exists.
try:
    from sqlalchemy import Column, String, Table, create_engine
    from sqlalchemy.orm import DeclarativeBase, Mapped, Session, clear_mappers, mapped_column, registry
    from sqlalchemy.types import TypeDecorator

    class MoneyType(TypeDecorator):
        impl = String
        cache_ok = True

        def process_bind_param(self, value, dialect):
            return None if value is None else f'{value.amount}:{value.currency}'

        def process_result_value(self, value, dialect):
            if value is None:
                return None
            amount, currency = value.split(':')
            return Money(int(amount), currency)

    # (a) imperative: the real Account, unmodified, with the table described
    # separately.
    reg = registry()
    reg.map_imperatively(
        Account,
        Table(
            'accounts',
            reg.metadata,
            Column('holder', String, primary_key=True),
            Column('balance', MoneyType, nullable=False),
        ),
    )
    engine = create_engine('sqlite://')
    reg.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account('Alice', Money(1000)))
        session.add(Account('Bob', Money(0)))
        session.commit()

    def imperative_pair():
        session = Session(engine)
        return session.get(Account, 'Alice'), session.get(Account, 'Bob')

    check('SQLAlchemy imperative (from the DB)', imperative_pair)

    # (b) declarative: the framework becomes part of the domain class.
    class Base(DeclarativeBase):
        pass

    class DeclarativeAccount(Base):
        __tablename__ = 'declarative_accounts'
        holder: Mapped[str] = mapped_column(primary_key=True)
        balance: Mapped[Money] = mapped_column(MoneyType)

        def debit(self, m):
            self.balance = self.balance - m

        def credit(self, m):
            self.balance = self.balance + m

    check(
        'SQLAlchemy declarative',
        lambda: (
            DeclarativeAccount(holder='Alice', balance=Money(1000)),
            DeclarativeAccount(holder='Bob', balance=Money(0)),
        ),
    )
    clear_mappers()
except ImportError:
    print('  (sqlalchemy not installed, 2 lines skipped)')

try:
    from pydantic import BaseModel

    class PydanticAccount(BaseModel):
        holder: str
        balance: Money
        model_config = {'arbitrary_types_allowed': True}

        def debit(self, m):
            self.balance = self.balance - m

        def credit(self, m):
            self.balance = self.balance + m

    check(
        'pydantic v2 BaseModel',
        lambda: (
            PydanticAccount(holder='Alice', balance=Money(1000)),
            PydanticAccount(holder='Bob', balance=Money(0)),
        ),
    )
except ImportError:
    print('  (pydantic not installed, skipped)')

try:
    import attrs

    @attrs.define  # slots=True is the default
    class AttrsAccount:
        holder: str
        balance: Money

        def debit(self, m):
            self.balance = self.balance - m

        def credit(self, m):
            self.balance = self.balance + m

    check(
        'attrs @define (slots by default)',
        lambda: (AttrsAccount('Alice', Money(1000)), AttrsAccount('Bob', Money(0))),
    )
except ImportError:
    print('  (attrs not installed, skipped)')


# The FrozenAccount from section 5b, reused: it is the same case.
check('@dataclass(frozen=True)', lambda: (FrozenAccount('Alice', Money(1000)), FrozenAccount('Bob', Money(0))))

print()
print('  Class binding works only on plain Python domain objects,')
print('  which is what DCI asks for in any case.')
