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
