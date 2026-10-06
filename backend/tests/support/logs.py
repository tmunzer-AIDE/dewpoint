# SPDX-License-Identifier: Apache-2.0
"""What structlog writes, as text: each line as the configured processors render it."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import structlog


@contextmanager
def rendered() -> Iterator[Callable[[], list[str]]]:
    """The lines structlog renders from here on: with its defaults until the code under test configures it. Only the
    output's destination is replaced (a configuration that names none keeps it); the defaults are back afterwards."""
    structlog.reset_defaults()
    factory = structlog.testing.CapturingLoggerFactory()
    structlog.configure(logger_factory=factory)
    try:
        yield lambda: [str(call.args[0]) for call in factory.logger.calls]
    finally:
        structlog.reset_defaults()
