"""A bank transfer, implemented several ways so the designs can be compared.

The canonical DCI example, and the domain of both posts in the series. The DCI
mechanism itself is `banking.dci` -- a module rather than the package, because
DCI is the mechanism this domain is written with, not the thing being modelled.

The layout follows the three letters, plus two modules for comparison::

    banking.data          what the objects are        (Account, Money)
    banking.roles         what they do here           (SourceAccount, ...)
    banking.contexts      the use cases, reified      (MoneyTransferContext, ...)
    banking.dci           the machinery that binds a role to an object
    banking.services      the same use case as a service, without the mechanism
    banking.alternatives  the designs DCI argues against, plus role-as-wrapper
"""
