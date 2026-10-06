# SPDX-License-Identifier: Apache-2.0
"""Juniper Mist (plugins-3): its connection type (D11) and a node per curated operation (D23), generated from the
policy map (D28) and the vendored OAS (D2)."""

from dewpoint.plugins.mist.connection import MIST
from dewpoint.plugins.mist.nodes import NODES
from dewpoint.sdk import Plugin

PLUGIN = Plugin(name="mist", version="1.0.0", nodes=NODES, connection_types=(MIST,))
