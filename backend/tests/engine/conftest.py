# SPDX-License-Identifier: Apache-2.0
"""The engine is pure (no database): its tests override the root conftest's autouse database cleanup, so they run
without Postgres, including in the Linux CEL gate job."""

import pytest


@pytest.fixture(autouse=True)
def clean_db() -> None:
    return None
