"""The role as a wrapper: DCI's structure without role binding, and without identity.

`SourceWrapper` and `WrappedTransfer` are one design and live in one module:
the wrapper holds the context and the context builds the wrapper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from banking.data.account import InsufficientFundsError

if TYPE_CHECKING:
    from banking.data.account import AccountLike
    from banking.data.money import Money


class SourceWrapper:
    """The role as a wrapper: DCI's structure without role binding or identity.

    This form has no `__slots__` limitation and no concurrency limitation, the
    type checker follows it, and it needs no explanation to read.

    The wrapper is not the account, however. Storing it, comparing it by
    identity, passing it to code that calls `isinstance`, or using it in a
    `set` or as a dictionary key all behave incorrectly. This is the identity
    problem of the Decorator pattern, which Reenskaug and Coplien cite when
    they observe that most GoF patterns break object identity to achieve their
    effect. What is lost is the property that distinguished DCI from passing
    the object to a function: here the object does not play the role, it is
    held inside another object that does.
    """

    def __init__(self, account: AccountLike, ctx: WrappedTransfer) -> None:
        """Wrap `account` for the duration of `ctx`."""
        self._account = account
        self._ctx = ctx

    def __getattr__(self, name: str) -> Any:
        """Forward anything not defined here to the wrapped account."""
        return getattr(self._account, name)

    def transfer(self, amount: Money) -> None:
        """Move `amount` to the context's destination."""
        if self._account.balance < amount:
            raise InsufficientFundsError(self._account.holder)
        self._account.debit(amount)
        self._ctx.destination.credit(amount)


class WrappedTransfer:
    """The same use case as `MoneyTransferContext`, built out of wrappers."""

    def __init__(self, source: AccountLike, destination: AccountLike, amount: Money) -> None:
        """Cast `source` and `destination` for a transfer of `amount`."""
        self.source = source
        self.destination = destination
        self.amount = amount

    def execute(self) -> None:
        """Run the use case."""
        SourceWrapper(self.source, self).transfer(self.amount)
