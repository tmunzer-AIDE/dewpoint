# SPDX-License-Identifier: Apache-2.0
"""Walks over CEL ASTs (parsed or checked, same node ids): children, scoping, select chains and types.

A *chain* is a run of field selections starting at a global identifier: `steps.a.output.name`. On a checked AST a
typed path arrives as one dotted identifier (`steps.a.output.devices`), which splits back into the same chain.
Comprehension variables shadow globals, as they do in the checker and the runtime."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from dewpoint.engine.cel.proto import checked_pb2, syntax_pb2

Expr = syntax_pb2.Expr  # the parsed and checked ASTs share the message type
Path = tuple[str, ...]  # (root, field, field, ...)
NON_JSON: frozenset[str] = frozenset({"non-json"})  # a result type with no JSON form (bytes, type values)
_PRIMITIVE_JSON = {1: "boolean", 2: "integer", 3: "integer", 4: "number", 5: "string"}  # BYTES (6) has none


@dataclass(frozen=True)
class Chain:
    path: Path  # root first; for a presence test, the tested field is last
    presence: bool  # `has(...)`: only whether the last field exists is observed
    expr_id: int
    ident: str  # the global identifier the chain starts from: a root, or a dotted typed path

    @property
    def root(self) -> str:
        return self.path[0]


def children(e: Expr) -> list[Expr]:
    kind = e.WhichOneof("expr_kind")
    if kind == "select_expr":
        return [e.select_expr.operand]
    if kind == "call_expr":
        target = [e.call_expr.target] if e.call_expr.HasField("target") else []
        return [*target, *e.call_expr.args]
    if kind == "list_expr":
        return list(e.list_expr.elements)
    if kind == "struct_expr":
        out: list[Expr] = []
        for entry in e.struct_expr.entries:
            if entry.HasField("map_key"):
                out.append(entry.map_key)
            out.append(entry.value)
        return out
    if kind == "comprehension_expr":
        ce = e.comprehension_expr
        return [ce.iter_range, ce.accu_init, ce.loop_condition, ce.loop_step, ce.result]
    return []


def walk(e: Expr) -> Iterator[Expr]:
    stack = [e]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(children(node)))


def operands(e: Expr) -> list[Expr]:
    """A call's operands: the receiver of a member call first, then the arguments."""
    return children(e) if e.WhichOneof("expr_kind") == "call_expr" else []


def scoped(e: Expr, scope: frozenset[str]) -> Iterator[tuple[Expr, frozenset[str]]]:
    """Every node with the local names in scope where it is evaluated."""
    stack = [(e, scope)]
    while stack:
        node, names = stack.pop()
        yield node, names
        if node.WhichOneof("expr_kind") == "comprehension_expr":
            ce = node.comprehension_expr
            body = names | {ce.iter_var, ce.accu_var}
            parts = [(ce.iter_range, names), (ce.accu_init, names), (ce.loop_condition, body), (ce.loop_step, body)]
            parts.append((ce.result, names | {ce.accu_var}))
            stack.extend(reversed(parts))
        else:
            stack.extend((child, names) for child in reversed(children(node)))


INDEX = "_[_]"
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NOT_SELECTABLE = frozenset({"in", "true", "false", "null"})  # CEL can't select these as fields


def field_key(e: Expr) -> str | None:
    """The key of `m["a"]` when it could have been written `m.a`: the same chain, checked the same way."""
    if e.WhichOneof("expr_kind") != "const_expr" or e.const_expr.WhichOneof("constant_kind") != "string_value":
        return None
    key = str(e.const_expr.string_value)
    return key if _FIELD.fullmatch(key) and key not in _NOT_SELECTABLE else None


def _step(node: Expr) -> tuple[str, Expr] | None:
    """One link of a chain: a field select, or an index by a field-like literal key."""
    kind = node.WhichOneof("expr_kind")
    if kind == "select_expr" and not node.select_expr.test_only:
        return node.select_expr.field, node.select_expr.operand
    if kind == "call_expr" and node.call_expr.function == INDEX and len(node.call_expr.args) == 2:
        key = field_key(node.call_expr.args[1])
        return (key, node.call_expr.args[0]) if key is not None else None
    return None


def _chain(e: Expr, scope: frozenset[str]) -> tuple[str, Path] | None:
    fields: list[str] = []
    node = e
    while (link := _step(node)) is not None:
        fields.append(link[0])
        node = link[1]
    if node.WhichOneof("expr_kind") != "ident_expr":
        return None
    name = node.ident_expr.name
    if name in scope:
        return None
    return name, (*name.split("."), *reversed(fields))


def chain_path(e: Expr, scope: frozenset[str]) -> Path | None:
    """The chain an ident, a (non-test) select or a field-like index denotes, or None if it isn't a chain from a
    global."""
    found = _chain(e, scope)
    return found[1] if found is not None else None


def chains(root: Expr) -> list[Chain]:
    """Maximal chains in evaluation order. A chain's own operands are not reported separately."""
    out: list[Chain] = []
    stack: list[tuple[Expr, frozenset[str]]] = [(root, frozenset())]
    while stack:
        e, scope = stack.pop()
        kind = e.WhichOneof("expr_kind")
        if kind == "select_expr" and e.select_expr.test_only:
            base = _chain(e.select_expr.operand, scope)
            if base is not None:
                out.append(Chain((*base[1], e.select_expr.field), True, e.id, base[0]))
                continue
        elif kind in ("select_expr", "ident_expr", "call_expr"):
            found = _chain(e, scope)
            if found is not None:
                out.append(Chain(found[1], False, e.id, found[0]))
                continue
        if kind == "comprehension_expr":
            ce = e.comprehension_expr
            body = scope | {ce.iter_var, ce.accu_var}
            parts = [(ce.iter_range, scope), (ce.accu_init, scope), (ce.loop_condition, body), (ce.loop_step, body)]
            parts.append((ce.result, scope | {ce.accu_var}))
            stack.extend(reversed(parts))
        else:
            stack.extend((child, scope) for child in reversed(children(e)))
    return out


def keyed_chains(root: Expr) -> list[Path]:
    """Chains indexed by a key that isn't a field name: one chosen at run time, or a literal like "a-b"."""
    out: list[Path] = []
    for e, scope in scoped(root, frozenset()):
        if e.WhichOneof("expr_kind") == "call_expr" and e.call_expr.function == INDEX and len(e.call_expr.args) == 2:
            if field_key(e.call_expr.args[1]) is None and (found := _chain(e.call_expr.args[0], scope)) is not None:
                out.append(found[1])
    return out


def global_idents(root: Expr) -> list[str]:
    """Global identifiers the expression reads (dotted for typed paths), sorted, each once."""
    names = {
        e.ident_expr.name
        for e, scope in scoped(root, frozenset())
        if e.WhichOneof("expr_kind") == "ident_expr" and e.ident_expr.name not in scope
    }
    return sorted(names)


def called_functions(root: Expr) -> set[str]:
    return {e.call_expr.function for e in walk(root) if e.WhichOneof("expr_kind") == "call_expr"}


def comprehension_depth(root: Expr) -> int:
    """Nesting that multiplies work: a comprehension inside another one's condition or step. A comprehension in a
    range, an initial value or a result runs once and doesn't nest."""
    best = 0
    stack = [(root, 0)]
    while stack:
        e, depth = stack.pop()
        if e.WhichOneof("expr_kind") == "comprehension_expr":
            ce = e.comprehension_expr
            depth += 1
            best = max(best, depth)
            stack += [(ce.loop_condition, depth), (ce.loop_step, depth)]
            stack += [(ce.iter_range, depth - 1), (ce.accu_init, depth - 1), (ce.result, depth - 1)]
        else:
            stack += [(child, depth) for child in children(e)]
    return best


def type_kind(checked: checked_pb2.CheckedExpr, expr_id: int) -> str:
    t = checked.type_map.get(expr_id)
    return (t.WhichOneof("type_kind") or "dyn") if t is not None else "dyn"


def overloads(checked: checked_pb2.CheckedExpr, expr_id: int) -> tuple[str, ...]:
    ref = checked.reference_map.get(expr_id)
    return tuple(ref.overload_id) if ref is not None else ()


def json_types(t: checked_pb2.Type | None) -> frozenset[str] | None:
    """The JSON types a checked CEL type can produce after canonicalization (spec §5.8). None: unknown (dyn).
    NON_JSON: a type canonicalization always rejects."""
    if t is None:
        return None
    kind = t.WhichOneof("type_kind")
    if kind in (None, "dyn", "type_param"):
        return None
    if kind == "null":
        return frozenset({"null"})
    if kind == "primitive":
        name = _PRIMITIVE_JSON.get(t.primitive)
        return frozenset({name}) if name else NON_JSON
    if kind == "wrapper":
        name = _PRIMITIVE_JSON.get(t.wrapper)
        return frozenset({name, "null"}) if name else NON_JSON
    if kind == "well_known":
        return frozenset({"string"}) if t.well_known in (2, 3) else None  # TIMESTAMP, DURATION; ANY is unknown
    if kind == "list_type":
        return frozenset({"array"})
    if kind == "map_type":
        return frozenset({"object"})
    return NON_JSON  # type values, errors, functions, messages, abstract types
