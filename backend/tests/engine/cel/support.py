# SPDX-License-Identifier: Apache-2.0
"""Build expression records the way publish does, without a workflow graph."""

from collections.abc import Mapping

from dewpoint.engine.cel import ast, classify, record, runtime
from dewpoint.engine.cel import types as T

ROOT_DECLS = {"trigger": T.MAP, "steps": T.MAP, "vars": T.MAP, "loops": T.MAP, "run": T.MAP}


def make_record(expr: str, typed: Mapping[str, str] | None = None, *, item: bool = False) -> record.ExpressionRecord:
    decls = {**ROOT_DECLS, **({"item": T.DYN, "index": T.INT} if item else {}), **(typed or {})}
    checked = runtime.compile_checked(expr, decls).checked
    c = classify.classify(expr, checked)
    return record.ExpressionRecord(
        node=None,
        field="/test",
        expr=expr,
        declarations=decls,
        idents=tuple(ast.global_idents(checked.expr)),
        projections=record.projections(ast.chains(checked.expr), decls),
        mode=c.mode,
        reason=c.reason,
        iterations=c.iterations,
        bytes=c.bytes,
        work=c.work,
    )


def nested_maps(depth: int) -> str:
    """`[1].map(v0, [1].map(v1, ... "s"))`: each map is six message levels of the runtime's AST, so 17 of them pass the
    protobuf decoder's limit (100) while the parser, whose limit is 32, still accepts them."""
    return "".join(f"[1].map(v{i}, " for i in range(depth)) + '"s"' + ")" * depth
