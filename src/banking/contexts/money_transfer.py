"""Context: the money transfer use case, reified once per binder.

The four classes below are the same use case, the same three roles and the
same script, bound four different ways. Nothing underneath the context
changes: the roles are plain classes, and neither they nor `Account` have any
knowledge of which mechanism attached them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from banking.dci import Context, InstanceContext, SerializedContext, TransparentContext
from banking.roles.money_transfer import DestinationAccount, SourceAccount, TransferAmount

if TYPE_CHECKING:
    from banking.data.account import AccountLike
    from banking.data.money import Money


class MoneyTransferContext(Context):
    """Two accounts and an amount, for the duration of the transfer.

    This is what DCI provides: the whole use case in one place, in a single
    line -- the source transfers. The `with self` block is the period during
    which the three participants play their parts. Outside it they are an
    account, an account and an amount, and `transfer` does not exist on any of
    them.
    """

    roles: ClassVar[dict[str, type]] = {
        'source': SourceAccount,
        'destination': DestinationAccount,
        'amount': TransferAmount,
    }

    def __init__(self, source: AccountLike, destination: AccountLike, amount: Money) -> None:
        """Cast `source`, `destination` and `amount` for one transfer.

        The participants are typed structurally on purpose. Role binding never
        required a particular class, only the protocol, and stating that is
        what allows the tests to pass a slotted or ORM-mapped account without
        suppressing a type error.
        """
        self.source = source
        self.destination = destination
        self.amount = amount

    def run_script(self) -> None:
        """Run the interaction, with the roles assumed already bound.

        Separate from `execute()` so that a caller already inside the context
        -- a test holding the roles open across a thread switch, for example --
        can run the script without re-entering.

        The `cast` records a runtime fact in one place. Inside the `with`,
        `self.source` is an `Account@SourceAccount` and does have
        `.transfer()`, but that class is built at runtime, exists in no source
        file, and cannot be shown to a type checker. This is an assertion, not
        a suppressed diagnostic.
        """
        cast('SourceAccount', self.source).transfer()

    def execute(self) -> None:
        """Run the use case: the source transfers."""
        with self:
            self.run_script()


class TransparentMoneyTransferContext(TransparentContext, MoneyTransferContext):
    """The same transfer, with the synthesized class keeping the data class's name.

    Declared as a combination of the binder and the use case, which is what it
    is: `TransparentContext` supplies `_bind`, and `MoneyTransferContext`
    supplies the roles, the participants and the script. Nothing is repeated.

    `InstanceMoneyTransferContext` below cannot be declared this way, because
    its binder does not derive from `Context`, which is why that class repeats
    the body.
    """


class SerializedMoneyTransferContext(SerializedContext, MoneyTransferContext):
    """The same transfer, with all three participants locked for the duration.

    The only one of the four that can be run from a thread pool. Two transfers
    out of the same account are serialized rather than colliding, and two
    transfers that share no participant run in parallel.
    """


class InstanceMoneyTransferContext(InstanceContext):
    """The same transfer, with the roles bound on the instance, not the class.

    Identical in everything a caller can observe -- same participants, same
    script, same outcome -- and different in what the language can observe. It
    runs where `MoneyTransferContext` refuses (frozen dataclasses,
    declaratively mapped ORM entities), and it leaves `type(source)`
    unchanged, so a traceback names a class that exists.

    It is an alternative rather than a replacement, for the reasons given in
    `banking.dci.InstanceContext`: a role cannot contribute a special method,
    and pickling fails on load rather than on dump.
    `tests/unit/test_instance_roles.py` asserts both sides of the trade.

    The roles dictionary is taken from `MoneyTransferContext` rather than
    restated: which object plays which part is a property of the use case, not
    of the mechanism binding them.
    """

    roles: ClassVar[dict[str, type]] = dict(MoneyTransferContext.roles)

    def __init__(self, source: AccountLike, destination: AccountLike, amount: Money) -> None:
        """Cast `source`, `destination` and `amount` for one transfer."""
        self.source = source
        self.destination = destination
        self.amount = amount

    def run_script(self) -> None:
        """Run the interaction, with the roles assumed already bound.

        The `cast` is present for a related reason. There is no runtime-built
        class here, but `self.source` is typed as an `AccountLike` and only
        acquires `.transfer()` inside the `with`. A type checker cannot see a
        method written in through `object.__setattr__`.
        """
        cast('SourceAccount', self.source).transfer()

    def execute(self) -> None:
        """Run the use case: the source transfers."""
        with self:
            self.run_script()
