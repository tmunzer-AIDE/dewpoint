# SPDX-License-Identifier: Apache-2.0
from dewpoint.engine.registry.catalog import Catalog, spec_from_manifest
from dewpoint.sdk import Plugin


def catalog(*plugins: Plugin, states: dict[str, str] | None = None) -> Catalog:
    wanted = states or {}
    return Catalog(
        spec_from_manifest(n, wanted.get(f"{n['type']}@{n['version']}", "active"))
        for p in plugins
        for n in p.manifest()["nodes"]
    )
