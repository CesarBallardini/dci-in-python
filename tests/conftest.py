"""Shared fixtures for the whole test suite, and the skips for runtimes without threads or processes."""

from __future__ import annotations

import asyncio
import sys
import threading

import pytest

from banking.data.account import Account
from banking.data.money import Money


@pytest.fixture
def alice() -> Account:
    """An account with money in it, ready to be a source."""
    return Account('Alice', Money(1000))


@pytest.fixture
def bob() -> Account:
    """An empty account, ready to be a destination."""
    return Account('Bob', Money(0))


def _a_thread_starts() -> bool:
    """Whether this runtime can start an OS thread. Pyodide cannot, and raises on `start()`."""
    thread = threading.Thread(target=lambda: None)
    try:
        thread.start()
    except RuntimeError:
        return False
    thread.join()
    return True


def _an_event_loop_runs() -> bool:
    """Whether synchronous code can run an event loop to completion.

    Two things prevent it. Pyodide can only where the JavaScript engine supports
    stack switching (JSPI), because blocking on the loop means suspending the
    WebAssembly stack. And desktop CPython refuses where a loop is already
    running in this thread, which is the case for a test run started from a
    notebook cell. Pyodide's loop, given JSPI, accepts it there as well.
    """

    async def nothing() -> None:
        return None

    probe = nothing()
    try:
        asyncio.run(probe)
    except RuntimeError:
        probe.close()  # refused before it started; closing it says so, rather than warning it was never awaited
        return False
    return True


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip the tests that need a capability this runtime does not have.

    The probes run only if a collected test carries the marker, and on the
    desktop every probe succeeds, so nothing is skipped there. A subprocess is
    not probed: CPython documents `subprocess` as unavailable on Emscripten and
    WASI, so the platform is the fact.
    """
    probes = {
        'threads': (_a_thread_starts, 'this runtime cannot start a thread'),
        'event_loop': (_an_event_loop_runs, 'cannot run an event loop here: unsupported, or one is already running'),
        'subprocess': (lambda: sys.platform not in {'emscripten', 'wasi'}, 'this runtime has no processes'),
    }
    missing: dict[str, str] = {}
    for marker, (available, reason) in probes.items():
        if any(item.get_closest_marker(marker) for item in items) and not available():
            missing[marker] = reason
    for item in items:
        for marker, reason in missing.items():
            if item.get_closest_marker(marker):
                item.add_marker(pytest.mark.skip(reason=reason))
