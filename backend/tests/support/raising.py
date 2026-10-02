# SPDX-License-Identifier: Apache-2.0
"""Code that raises, for the worker's log rules (engine 2b spec §6.7). It's a support module, loaded from its source:
pytest's loader for test files gives no code to read, so nothing in a test file is proven to be code."""


class Declared(Exception):
    """A class its module's code declares."""


def raises(text: str) -> None:
    raise RuntimeError(text)
