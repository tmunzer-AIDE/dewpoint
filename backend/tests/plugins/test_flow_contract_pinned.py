# SPDX-License-Identifier: Apache-2.0
"""The flow plugin's node contracts are pinned (plugins-3 D12): published versions depend on them, so a new manifest
key or SDK change must leave every flow@1 hash as it was. The values were computed on origin/main 6482c53, before
sub-project 3, and on its first slice, equal."""

from dewpoint.engine.registry.catalog import contract_hash
from dewpoint.plugins.flow import PLUGIN

PINNED = {
    "flow.delay@1": "f57a1bd85ec758808c2a3f50053f521a2743d227bd752965da70169774c33819",
    "flow.fail@1": "27e01c0f9f75ff5ce4ed5f6a7a223c0c7e747731ef397187dc1b048ae4035081",
    "flow.filter@1": "ff81e1679cd6a95dbaaa2d1a91ede6f28fc59bd2fc1fa4057bb5b178245e1981",
    "flow.if@1": "450d4f6889e132379a0117c9f76bd6a47d16634df0994c5bf3268ae037600155",
    "flow.loop@1": "c0ecfbedd9da8f79e079284da908c724365389ace289c739aa667636b9aa7cfc",
    "flow.run_workflow@1": "8cfca502d6921364bfc03cfe0294611e373bbde4de0a1b324805a2c85288b44a",
    "flow.set_variables@1": "381551611012e8fa4a099e086abf486f2c79bd61f444b3e8aa4585abbaef7730",
    "flow.stop@1": "0de2021f6b47344c6dbb107c8c6a9db4652f1ab86f5d3b7685401b77d6131207",
    "flow.switch@1": "f5ca003f7f26e29997f99fdda6e9a88b4240a3eb248e83e3a2e57716c8cd6e8d",
    "flow.transform@1": "b90118627279211eaee972cd8643a00d8a47a90ef4fd81446d2be2f3ce123c7d",
    "flow.wait_until@1": "61f1e42f11c14559dcdc134cd60cbc7120601cf37e426ed76aa3a103cccc1df9",
}


def test_flow_contract_hashes_are_unchanged() -> None:
    found = {f"{n['type']}@{n['version']}": contract_hash(n) for n in PLUGIN.manifest()["nodes"]}
    assert found == PINNED
