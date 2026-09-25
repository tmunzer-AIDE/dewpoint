# SPDX-License-Identifier: Apache-2.0
from dewpoint.plugins.flow.nodes import NODES
from dewpoint.sdk import Plugin

PLUGIN = Plugin(name="flow", version="1.0.0", nodes=NODES)
