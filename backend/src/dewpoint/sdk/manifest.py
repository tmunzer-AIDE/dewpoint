# SPDX-License-Identifier: Apache-2.0
import re
from dataclasses import dataclass
from typing import Any

from dewpoint.sdk.node import PORT_RE, RESERVED_PORTS, TYPE_RE, Node, NodeKind, SideEffect
from dewpoint.sdk.version import SDK_VERSION

PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class ManifestError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _problems(node: type[Node]) -> list[str]:
    missing = [a for a in ("type", "version", "title") if not hasattr(node, a)]
    if missing:
        return [f"{node.__name__}: missing {', '.join(missing)}"]
    name = f"{node.type}@{node.version}"
    out: list[str] = []
    if not TYPE_RE.match(node.type):
        out.append(f"{name}: type must look like 'plugin.name'")
    if isinstance(node.version, bool) or not isinstance(node.version, int) or node.version < 1:
        out.append(f"{name}: version must be an integer ≥ 1")
    if len(set(node.ports)) != len(node.ports):
        out.append(f"{name}: duplicate ports")
    for port in node.ports:
        if not PORT_RE.match(port) or port in RESERVED_PORTS:
            out.append(f"{name}: invalid port {port!r}")
    if node.dynamic_ports is not None and node.dynamic_ports not in node.Config.model_fields:
        out.append(f"{name}: dynamic_ports names unknown config field {node.dynamic_ports!r}")
    if node.retry.max_attempts < 1:
        out.append(f"{name}: retry.max_attempts must be ≥ 1")
    if node.timeout.total_seconds() <= 0:
        out.append(f"{name}: timeout must be positive")
    if node.kind is NodeKind.ACTION:
        if node.run is Node.run:
            out.append(f"{name}: action nodes must implement run()")
        if node.side_effect is SideEffect.RECONCILABLE and node.reconcile is Node.reconcile:
            out.append(f"{name}: RECONCILABLE nodes must implement reconcile()")
    return out


def node_manifest(node: type[Node]) -> dict[str, Any]:
    problems = _problems(node)
    if problems:
        raise ManifestError(problems)
    r = node.retry
    return {
        "type": node.type,
        "version": node.version,
        "kind": node.kind.value,
        "title": node.title,
        "description": node.description,
        "ports": list(node.ports),
        "dynamic_ports": node.dynamic_ports,
        "config_schema": node.Config.model_json_schema(mode="validation"),
        "output_schema": node.Output.model_json_schema(mode="serialization"),
        "credentials": list(node.credentials),
        "capabilities": sorted(node.capabilities),
        "side_effect": node.side_effect.value,
        "retry": {
            "max_attempts": r.max_attempts,
            "initial_interval_s": r.initial_interval.total_seconds(),
            "backoff": r.backoff,
            "max_interval_s": r.max_interval.total_seconds(),
            "non_retryable": list(r.non_retryable),
        },
        "timeout_s": node.timeout.total_seconds(),
    }


@dataclass(frozen=True)
class Plugin:
    name: str
    version: str
    nodes: tuple[type[Node], ...]

    def manifest(self) -> dict[str, Any]:
        problems: list[str] = []
        if not PLUGIN_NAME_RE.match(self.name):
            problems.append(f"plugin name {self.name!r} must be a lowercase identifier")
        nodes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in self.nodes:
            try:
                m = node_manifest(node)
            except ManifestError as e:
                problems.extend(e.problems)
                continue
            ref = f"{m['type']}@{m['version']}"
            if not m["type"].startswith(f"{self.name}."):
                problems.append(f"{ref}: type must start with '{self.name}.'")
            if ref in seen:
                problems.append(f"{ref}: duplicate node type version")
            seen.add(ref)
            nodes.append(m)
        if problems:
            raise ManifestError(problems)
        return {"name": self.name, "version": self.version, "sdk_version": SDK_VERSION, "nodes": nodes}
