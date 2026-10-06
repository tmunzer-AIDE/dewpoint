# SPDX-License-Identifier: Apache-2.0
"""Juniper Mist (plugins-3): its connection type (D11) and a node per curated operation (D23), generated from the
policy map (D28) and the vendored OAS (D2), the two any-endpoint nodes (D14), and its webhook trigger (D17)."""

from dewpoint.plugins.mist import api
from dewpoint.plugins.mist.connection import MIST
from dewpoint.plugins.mist.nodes import NODES
from dewpoint.plugins.mist.webhook import WEBHOOK
from dewpoint.sdk import Plugin

PLUGIN = Plugin(name="mist", version="1.0.0", nodes=NODES + api.NODES, connection_types=(MIST,), triggers=(WEBHOOK,))
