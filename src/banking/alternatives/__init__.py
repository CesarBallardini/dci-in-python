"""The same transfer without DCI: the two conventional designs, and a wrapper.

These live in the package rather than only in prose so that the comparison is
code that can be run and tested. Nothing else in `banking` imports them.

One design per module, each with its own test file:

=====================================  ==========================  =============================
module                                 contents                    tests
=====================================  ==========================  =============================
`banking.alternatives.fat_account`     `FatAccount`                `test_fat_account.py`
`banking.alternatives.anemic_service`  `AnemicAccount`,            `test_anemic_service.py`
                                       `TransferService`
`banking.alternatives.role_as_wrapper` `SourceWrapper`,            `test_role_as_wrapper.py`
                                       `WrappedTransfer`
=====================================  ==========================  =============================

`APPROACHES.md` compares all three against DCI and against the service in
`banking.services.money_transfer`.
"""

from __future__ import annotations

from banking.alternatives.anemic_service import AnemicAccount, TransferService
from banking.alternatives.fat_account import FatAccount
from banking.alternatives.role_as_wrapper import SourceWrapper, WrappedTransfer

__all__ = [
    'AnemicAccount',
    'FatAccount',
    'SourceWrapper',
    'TransferService',
    'WrappedTransfer',
]
