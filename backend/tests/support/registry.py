# SPDX-License-Identifier: Apache-2.0
from typing import Any

from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.plugins.flow import PLUGIN
from tests.support.plugins.testkit import TESTKIT


async def sync_test_plugins(sessionmaker: Any) -> None:
    """Register flow + testkit (and this build's CEL profile), as `dewpoint plugins sync` would."""
    async with sessionmaker() as s, s.begin():
        await sync_installed(s, [PLUGIN, TESTKIT])
