# SPDX-License-Identifier: Apache-2.0
"""Fixtures the erasure's tests share with admission's and the tick's: a published workflow (`ready`), and one with a
schedule (`scheduled`)."""

from tests.apps.dispatcher.test_schedule_tick import ready as scheduled  # noqa: F401
from tests.apps.test_admission import ready  # noqa: F401
