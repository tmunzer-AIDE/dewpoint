# SPDX-License-Identifier: Apache-2.0
"""Juniper Mist (plugins-3). For now only its connection type (D11); its nodes come with 3b."""

from dewpoint.plugins.mist.connection import MIST
from dewpoint.sdk import Plugin

PLUGIN = Plugin(name="mist", version="1.0.0", nodes=(), connection_types=(MIST,))
