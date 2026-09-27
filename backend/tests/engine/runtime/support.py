# SPDX-License-Identifier: Apache-2.0
"""Compile test graphs the way a published version is compiled: validated first, with its expression records."""

import uuid
from collections.abc import Mapping
from typing import Any

from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, validate
from dewpoint.engine.runtime.program import Program, compile_program
from dewpoint.engine.runtime.scheduler import Instance, Scheduler, iteration_key
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G
from tests.support.plugins.testkit import TESTKIT

MANIFESTS: dict[str, dict[str, Any]] = {
    f"{m['type']}@{m['version']}": m for p in (PLUGIN, TESTKIT) for m in p.manifest()["nodes"]
}
CATALOG = catalog(PLUGIN, TESTKIT)


def expressions(g: G, subflows: Mapping[uuid.UUID, SubflowInfo] | None = None) -> list[dict[str, Any]]:
    result = validate(g.build(), ValidationContext(catalog=CATALOG, subflows=subflows or {}))
    errors = [d.to_json() for d in result.diagnostics if d.severity == "error"]
    assert not errors, errors
    return [r.to_json() for r in result.expressions]


def program(g: G) -> Program:
    return compile_program(g.data(), MANIFESTS, expressions(g), CURRENT_CEL_PROFILE)


def name(s: Scheduler, inst: Instance) -> str:
    key = iteration_key(inst.scope)
    return f"{key}/{s.step(inst).key}" if key else s.step(inst).key
