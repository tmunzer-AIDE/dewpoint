# SPDX-License-Identifier: Apache-2.0
"""Presence facts from `has()` guards (spec §4.3, §5.10 `cel.conditional_ref`).

`facts_at` maps every node to the paths known to exist whenever that node's value can affect the result. CEL's `&&`
and `||` absorb an error when the other side decides the result, so each side is guarded by the other:
`has(steps.a.output) && steps.a.output.x > 1` and `steps.a.output.x > 1 && has(steps.a.output)` are both safe. The
condition of `c ? a : b` is not guarded by its branches."""

from dewpoint.engine.cel import ast

Facts = frozenset[ast.Path]
_NONE: Facts = frozenset()


def _prefixes(path: ast.Path) -> Facts:
    return frozenset(path[:k] for k in range(2, len(path) + 1))


def _args(e: ast.Expr, function: str, arity: int) -> list[ast.Expr] | None:
    if e.WhichOneof("expr_kind") != "call_expr" or e.call_expr.function != function:
        return None
    args = list(e.call_expr.args)
    return args if len(args) == arity and not e.call_expr.HasField("target") else None


def when_true(e: ast.Expr, scope: frozenset[str]) -> Facts:
    if e.WhichOneof("expr_kind") == "select_expr" and e.select_expr.test_only:
        base = ast.chain_path(e.select_expr.operand, scope)
        return _prefixes((*base, e.select_expr.field)) if base is not None else _NONE
    if (args := _args(e, "!_", 1)) is not None:
        return when_false(args[0], scope)
    if (args := _args(e, "_&&_", 2)) is not None:
        return when_true(args[0], scope) | when_true(args[1], scope)
    return _NONE


def when_false(e: ast.Expr, scope: frozenset[str]) -> Facts:
    if (args := _args(e, "!_", 1)) is not None:
        return when_true(args[0], scope)
    if (args := _args(e, "_||_", 2)) is not None:
        return when_false(args[0], scope) | when_false(args[1], scope)
    return _NONE


def facts_at(root: ast.Expr) -> dict[int, Facts]:
    out: dict[int, Facts] = {}
    stack: list[tuple[ast.Expr, frozenset[str], Facts]] = [(root, frozenset(), _NONE)]
    while stack:
        e, scope, facts = stack.pop()
        out[e.id] = facts
        if (args := _args(e, "_&&_", 2)) is not None:
            a, b = args
            stack += [(b, scope, facts | when_true(a, scope)), (a, scope, facts | when_true(b, scope))]
        elif (args := _args(e, "_||_", 2)) is not None:
            a, b = args
            stack += [(b, scope, facts | when_false(a, scope)), (a, scope, facts | when_false(b, scope))]
        elif (args := _args(e, "_?_:_", 3)) is not None:
            c, a, b = args
            stack += [
                (b, scope, facts | when_false(c, scope)),
                (a, scope, facts | when_true(c, scope)),
                (c, scope, facts),
            ]
        elif e.WhichOneof("expr_kind") == "comprehension_expr":
            ce = e.comprehension_expr
            body = scope | {ce.iter_var, ce.accu_var}
            stack += [(ce.result, scope | {ce.accu_var}, facts), (ce.loop_step, body, facts)]
            stack += [(ce.loop_condition, body, facts), (ce.accu_init, scope, facts), (ce.iter_range, scope, facts)]
        else:
            stack += [(child, scope, facts) for child in reversed(ast.children(e))]
    return out
