# SPDX-License-Identifier: Apache-2.0
"""Facts from guards (spec §4.3, §5.10 `cel.conditional_ref`): paths known to exist (`has()`), known not to be null
(`!= null`), or known to be objects (`type(x) == type({})`).

`facts_at` maps every node to the paths a kind of guard proves whenever that node's value can affect the result.
CEL's `&&` and `||` absorb an error when the other side decides the result, so each side is guarded by the other:
`has(steps.a.output) && steps.a.output.x > 1` and `steps.a.output.x > 1 && has(steps.a.output)` are both safe. The
condition of `c ? a : b` is not guarded by its branches. A guard proves only its own kind: a present value may still
be null, and `x != null` fails, rather than proves anything, when x is missing."""

from collections.abc import Callable

from dewpoint.engine.cel import ast

Facts = frozenset[ast.Path]
_NONE: Facts = frozenset()
Leaf = Callable[[ast.Expr, frozenset[str], bool], Facts]  # what a test proves when it is true (or false)


def _prefixes(path: ast.Path) -> Facts:
    return frozenset(path[:k] for k in range(2, len(path) + 1))


def _args(e: ast.Expr, function: str, arity: int) -> list[ast.Expr] | None:
    if e.WhichOneof("expr_kind") != "call_expr" or e.call_expr.function != function:
        return None
    args = list(e.call_expr.args)
    return args if len(args) == arity and not e.call_expr.HasField("target") else None


def presence(e: ast.Expr, scope: frozenset[str], truth: bool) -> Facts:
    """`has(a.b)`, when true: a.b exists, and so does everything it's read from."""
    if truth and e.WhichOneof("expr_kind") == "select_expr" and e.select_expr.test_only:
        base = ast.chain_path(e.select_expr.operand, scope)
        return _prefixes((*base, e.select_expr.field)) if base is not None else _NONE
    return _NONE


def _is_null(e: ast.Expr) -> bool:
    return e.WhichOneof("expr_kind") == "const_expr" and bool(e.const_expr.WhichOneof("constant_kind") == "null_value")


def non_null(e: ast.Expr, scope: frozenset[str], truth: bool) -> Facts:
    """`x != null` when true, `x == null` when false: x isn't null, nor is anything it's read from."""
    for function, holds in (("_!=_", truth), ("_==_", not truth)):
        if holds and (args := _args(e, function, 2)) is not None:
            for value, other in (args, args[::-1]):
                if _is_null(other) and (path := ast.chain_path(value, scope)) is not None:
                    return _prefixes(path)
    return _NONE


def _type_operand(e: ast.Expr) -> ast.Expr | None:
    """x, for `type(x)`."""
    return args[0] if (args := _args(e, "type", 1)) is not None else None


def _is_map_type(e: ast.Expr, scope: frozenset[str]) -> bool:
    """A map's type: `type({})`, spelled as a run can bind it; or the built-in `map`, never a comprehension's variable
    of that name (`[type("")].all(map, …)`), which validation refuses as a type's name (cel.type_name) but which still
    proves the shape, so a formula using it is told one thing."""
    if e.WhichOneof("expr_kind") == "ident_expr":
        return e.ident_expr.name == "map" and "map" not in scope
    operand = _type_operand(e)
    return (
        operand is not None
        and operand.WhichOneof("expr_kind") == "struct_expr"
        and not operand.struct_expr.message_name
        and len(operand.struct_expr.entries) == 0
    )


def shape(e: ast.Expr, scope: frozenset[str], truth: bool) -> Facts:
    """`type(x) == type({})` when true, `type(x) != type({})` when false: x is an object, and so is everything it's
    read from (4c-2a: a value its schema says may not be an object is guarded so before its fields are read)."""
    for function, holds in (("_==_", truth), ("_!=_", not truth)):
        if holds and (args := _args(e, function, 2)) is not None:
            for value, other in (args, args[::-1]):
                operand = _type_operand(value)
                if (
                    _is_map_type(other, scope)
                    and operand is not None
                    and (path := ast.chain_path(operand, scope)) is not None
                ):
                    return _prefixes(path)
    return _NONE


def when_true(e: ast.Expr, scope: frozenset[str], leaf: Leaf = presence) -> Facts:
    if (args := _args(e, "!_", 1)) is not None:
        return when_false(args[0], scope, leaf)
    if (args := _args(e, "_&&_", 2)) is not None:
        return when_true(args[0], scope, leaf) | when_true(args[1], scope, leaf)
    return leaf(e, scope, True)


def when_false(e: ast.Expr, scope: frozenset[str], leaf: Leaf = presence) -> Facts:
    if (args := _args(e, "!_", 1)) is not None:
        return when_true(args[0], scope, leaf)
    if (args := _args(e, "_||_", 2)) is not None:
        return when_false(args[0], scope, leaf) | when_false(args[1], scope, leaf)
    return leaf(e, scope, False)


def facts_at(root: ast.Expr, leaf: Leaf = presence) -> dict[int, Facts]:
    out: dict[int, Facts] = {}
    stack: list[tuple[ast.Expr, frozenset[str], Facts]] = [(root, frozenset(), _NONE)]
    while stack:
        e, scope, facts = stack.pop()
        out[e.id] = facts
        if (args := _args(e, "_&&_", 2)) is not None:
            a, b = args
            stack += [(b, scope, facts | when_true(a, scope, leaf)), (a, scope, facts | when_true(b, scope, leaf))]
        elif (args := _args(e, "_||_", 2)) is not None:
            a, b = args
            stack += [(b, scope, facts | when_false(a, scope, leaf)), (a, scope, facts | when_false(b, scope, leaf))]
        elif (args := _args(e, "_?_:_", 3)) is not None:
            c, a, b = args
            stack += [
                (b, scope, facts | when_false(c, scope, leaf)),
                (a, scope, facts | when_true(c, scope, leaf)),
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
