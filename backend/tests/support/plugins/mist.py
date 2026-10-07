# SPDX-License-Identifier: Apache-2.0
"""Mist's plugin as tests that need only its connection type sync it: the same name, version and declaration (so the
same declaration hash) without its 264 generated nodes, whose manifest takes about 12 s to check and 8 MB to store."""

from dewpoint.plugins.mist import PLUGIN
from dewpoint.sdk import Plugin

MIST_TYPE_ONLY = Plugin(name=PLUGIN.name, version=PLUGIN.version, nodes=(), connection_types=PLUGIN.connection_types)
