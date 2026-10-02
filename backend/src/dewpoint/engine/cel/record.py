# SPDX-License-Identifier: Apache-2.0
"""What publish stores for every CEL value (spec §4.1, §5.5), so the runtime never re-derives it.

The record carries everything evaluation needs besides the values: the declarations to compile with, which global
identifiers to bind, how to project each root down to what the expression reads, and the class with its bounds."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from dewpoint.engine.cel import ast


@dataclass(frozen=True)
class Projection:
    path: ast.Path  # root first; the empty tail means the whole root
    presence: bool  # only whether the last field exists matters


@dataclass(frozen=True)
class ExpressionRecord:
    node: str | None  # node id; None for workflow outputs
    field: str  # JSON pointer of the value (`/settings/outputs/<name>` for outputs)
    expr: str
    declarations: Mapping[str, str]  # identifier -> CEL type signature
    idents: tuple[str, ...]  # global identifiers the checked expression reads
    projections: tuple[Projection, ...]  # chains read from roots (not from typed paths)
    mode: Literal["local", "activity"]
    reason: str | None = None
    iterations: int | None = None
    bytes: int | None = None
    work: int | None = None
    tainted: bool = False  # it reads sensitive data (engine 2b spec §4.1): it runs in the evaluator, its result claimed

    def to_json(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "field": self.field,
            "expr": self.expr,
            "declarations": dict(sorted(self.declarations.items())),
            "idents": list(self.idents),
            "projections": [{"path": list(p.path), "presence": p.presence} for p in self.projections],
            "mode": self.mode,
            "reason": self.reason,
            "iterations": self.iterations,
            "bytes": self.bytes,
            "work": self.work,
            "tainted": self.tainted,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ExpressionRecord":
        return cls(
            node=data["node"],
            field=data["field"],
            expr=data["expr"],
            declarations=dict(data["declarations"]),
            idents=tuple(data["idents"]),
            projections=tuple(Projection(tuple(p["path"]), bool(p["presence"])) for p in data["projections"]),
            mode=data["mode"],
            reason=data["reason"],
            iterations=data["iterations"],
            bytes=data["bytes"],
            work=data["work"],
            tainted=bool(data.get("tainted", False)),
        )


def projections(chains: list[ast.Chain], declarations: Mapping[str, str]) -> tuple[Projection, ...]:
    """Chains that start at a root (not at a dotted typed path), each once, in a stable order."""
    found = {Projection(c.path, c.presence) for c in chains if "." not in c.ident and c.ident in declarations}
    return tuple(sorted(found, key=lambda p: (p.path, p.presence)))
