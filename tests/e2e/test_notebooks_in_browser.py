"""Every notebook, run in a real browser against the built JupyterLite site.

`make lite` builds the site into `_site/`; these tests serve it from a local
HTTP server, open each notebook in the Jupyter Notebook interface, run all its
cells on the Pyodide kernel, and read the outputs back from the page. They
check what the Node run in `make test-pyodide` cannot: that the browser loads
the kernel, that piplite finds the `banking` wheel served with the site, and
that the kernel reads `tests/` through the site's file system.

Excluded from `make test` by the `e2e` marker, because they need the built
site and installed browsers. `make test-e2e` provides both.
"""

from __future__ import annotations

import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

SITE = Path(__file__).resolve().parents[2] / '_site'

# Loading Pyodide from its CDN and installing the packages a notebook needs
# takes most of this; the cells themselves run in seconds.
NOTEBOOK_TIMEOUT_MS = 240_000


class QuietHandler(SimpleHTTPRequestHandler):
    """Serves the site without printing a line per request."""

    def log_message(self, format: str, *args: object) -> None:
        """Discard the request log."""


@pytest.fixture(scope='session')
def site_url() -> Iterator[str]:
    """The built site, served on a free local port for the whole session."""
    if not (SITE / 'index.html').is_file():
        pytest.fail(f'{SITE} has not been built; run `make lite` first')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(SITE)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    thread.join()


def run_all_cells(page: Page, url: str) -> str:
    """Open a notebook, run every cell, and return the text of every output once the last one has run."""
    page.goto(url)
    page.locator('.jp-Notebook').wait_for(timeout=NOTEBOOK_TIMEOUT_MS)
    page.locator('.lm-MenuBar-itemLabel', has_text=re.compile(r'^Run$')).click()
    page.locator('.lm-Menu-itemLabel', has_text=re.compile(r'^Run All Cells$')).click()
    last_cell = page.locator('.jp-CodeCell').last
    # A code cell's prompt reads `[*]` while it waits or runs and `[n]` once it has run.
    last_cell.locator('.jp-InputPrompt', has_text=re.compile(r'\[\d+\]')).wait_for(timeout=NOTEBOOK_TIMEOUT_MS)
    # The text content rather than the rendered text: the notebook does not
    # render cells scrolled out of view, so their rendered text is empty.
    return '\n'.join(page.locator('.jp-OutputArea-output').all_text_contents())


@pytest.mark.parametrize(
    ('notebook', 'expected'),
    [
        pytest.param(
            '01-the-mechanism.ipynb',
            [
                'the account defines transfer_to: True',
                'methods AnemicAccount defines: []',
                'inside:   type(a).__name__ = Account@SourceAccount',
                'same id outside? True',
            ],
            id='01',
        ),
        pytest.param(
            '02-four-binders.ipynb',
            [
                'InstanceContext      dumps succeeds, loads fails',
                'InstanceContext      inside the context, Money(5) < Money(1) -> False',
            ],
            id='02',
        ),
        pytest.param(
            '03-where-python-says-no.ipynb',
            [
                # Wrapped at 76 columns, as the post quotes it.
                "RuntimeError: Account already has 'transfer': instance binding will not\n"
                'overwrite it. Another context is playing this role, or the object defines\n'
                'that name itself.',
                "RuntimeError: can't start new thread",
                'InstanceContext      balance 1000002, and after both left the account is Account, with no role',
                'the next transfer out of it raises TypeError',
            ],
            id='03',
        ),
        pytest.param(
            '04-five-designs.ipynb',
            [
                'BREAKS SQLAlchemy declarative',
                'WORKS  SQLAlchemy declarative',
                'isinstance(roles.source, Account) -> False',
                # Only the service moves the money for an attrs class.
                'WORKS  attrs @define (slots by default)       -> 750 / 250',
            ],
            id='04',
        ),
        pytest.param('05-run-the-tests.ipynb', ['pytest exit code: 0'], id='05'),
    ],
)
def test_the_notebook_runs_in_the_browser(page: Page, site_url: str, notebook: str, expected: list[str]) -> None:
    """The notebook runs top to bottom on the Pyodide kernel, with no traceback and the outputs it has on the desktop.

    Every notebook reports its runtime first, so the run is shown to be
    CPython 3.14 compiled to WebAssembly rather than anything the test machine
    has installed.
    """
    outputs = run_all_cells(page, f'{site_url}/notebooks/index.html?path={notebook}')

    assert re.search(r'Python 3\.14\.\d+ on emscripten', outputs)
    assert 'Traceback' not in outputs
    for text in expected:
        assert text in outputs
