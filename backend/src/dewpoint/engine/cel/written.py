# SPDX-License-Identifier: Apache-2.0
"""Where the constants written into a CEL expression may land in its value (engine 2b spec §3.8, issue #79).

Publish refuses a value written at a sensitive position. A formula that reads run data can still carry a constant it
writes into its result (`"Bearer " + trigger.tok`, `trigger.n > 0 ? "…" : ""`). This walk follows each constant on
the parsed AST through what carries it, and stops at what doesn't (`CARRIES`, `STOPS`); a function neither names,
and a message built in the expression (a `google.protobuf.Struct`'s `fields` are its object's own keys), carry every
constant of their operands anywhere. Every constant counts — text, bytes, numbers, booleans, null — but empty text,
bytes or list joined by `+`, which writes nothing (as empty text beside a template's reference). An empty list or map
the author writes is written whole, as the literal is (an empty map's keys with it, so it counts where keys are
marked, as the literal `{}` does); one holding reads writes only the constants it holds. A macro's accumulator start
(`@result`, from `true`, `false`, `0` or an empty list) is the macro's, not the author's: it's never walked.

A position names where a constant may land: a path of map keys, list indexes, `ITEM` (any element of a list, whose
index a concatenation or a macro lost) and `VALUE` (any value of a map, under a key chosen at run time), then at most
one of `KEY` (a key of the map there: it stays a key until its own map is iterated or `sortedKeys` reads it) or `ANY`
(anything, keys included, anywhere at or under there).

Each node's result is remembered for the bindings of the names free in it, so a comprehension walking its step again
until its accumulator settles walks the comprehensions nested in it once: work stays linear in the expression's size
(nested macros would otherwise cost 2^depth)."""

import enum

from dewpoint.engine.cel.ast import Expr, children, operands


class Wild(enum.Enum):
    ANY = "any"
    ITEM = "item"
    VALUE = "value"
    KEY = "key"


Position = tuple[str | int | Wild, ...]
Reach = frozenset[Position]
NONE: Reach = frozenset()
WHOLE: Reach = frozenset({()})
ANYWHERE: Reach = frozenset({(Wild.ANY,)})
ELEMENTS: Reach = frozenset({(Wild.ITEM,)})
MACRO_ACCUMULATOR = "@result"
_ROUNDS = 4  # an accumulator's positions settle in two; past this, anywhere

STOPS = frozenset({
    "_==_", "_!=_", "_<_", "_<=_", "_>_", "_>=_", "_&&_", "_||_", "!_", "@in", "@not_strictly_false", "size",
    "contains", "startsWith", "endsWith", "matches", "type", "ipInCidr", "cidrContains",
})  # fmt: skip  # a boolean, a count or a type: none of its operands' constants
_SCALAR = frozenset({
    "int", "uint", "double", "string", "bytes", "bool", "timestamp", "duration", "macNormalize", "macOui",
    "getFullYear", "getMonth", "getDayOfYear", "getDayOfMonth", "getDate", "getDayOfWeek", "getHours", "getMinutes",
    "getSeconds", "getMilliseconds",
})  # fmt: skip  # a scalar made from its first operand (a getter's receiver; never its time zone)
_ARITHMETIC = frozenset({"_+_", "_-_", "_*_", "_/_", "_%_", "-_"})
CARRIES = _SCALAR | _ARITHMETIC | {"_?_:_", "_[_]", "dyn", "asList", "sortedKeys"}


def reaching(root: Expr) -> Reach:
    """Where constants written in the expression may land in its value."""
    return Walk().reach(root)


def _below(reach: Reach, key: str | int | None) -> Reach:
    """What a field read or an index by `key` (None: chosen at run time) gives of a value holding `reach`."""
    out: set[Position] = set()
    for p in reach:
        if not p or p[0] is Wild.KEY:
            continue  # a scalar has no part, and the value's own keys aren't a value
        if p[0] is Wild.ANY:
            out.add(p)
        elif p[0] in (Wild.ITEM, Wild.VALUE) or key is None or p[0] == key:
            out.add(p[1:])
    return frozenset(out)


def _elements(reach: Reach) -> Reach:
    """What iterating a value holding `reach` binds: a list's elements, a map's keys."""
    out: set[Position] = set()
    for p in reach:
        if not p:
            continue
        if p[0] is Wild.KEY:
            out.add(())  # the iterated map's own keys, bound as values
        elif p[0] is Wild.ANY:
            out.add(p)
        elif p[0] is Wild.ITEM or isinstance(p[0], int):
            out.add(p[1:])
        # a map's value (under a written key, or `VALUE`) isn't bound: iterating a map binds its keys
    return frozenset(out)


def _flat(reach: Reach) -> Reach:
    """Concatenation keeps a scalar whole and an element's place within it, at any index."""
    out: set[Position] = set()
    for p in reach:
        if not p or p[0] in (Wild.ANY, Wild.ITEM):
            out.add(p)
        elif isinstance(p[0], int):
            out.add((Wild.ITEM, *p[1:]))
        else:
            out.add((Wild.ANY,))  # a map's part or its keys: `+` joins no maps
    return frozenset(out)


def _empty(e: Expr) -> bool:
    """Text, bytes or a list written empty: joined by `+`, it writes nothing."""
    if e.WhichOneof("expr_kind") == "list_expr":
        return not e.list_expr.elements
    kind = e.const_expr.WhichOneof("constant_kind") if e.WhichOneof("expr_kind") == "const_expr" else None
    return kind in ("string_value", "bytes_value") and not getattr(e.const_expr, kind)


def _key(e: Expr) -> str | int | None:
    """A lookup's key when written as a constant."""
    if e.WhichOneof("expr_kind") != "const_expr":
        return None
    kind = e.const_expr.WhichOneof("constant_kind")
    if kind in ("string_value", "int64_value", "uint64_value"):
        found: str | int = getattr(e.const_expr, kind)
        return found
    return None


def _macro_start(ce: Expr.Comprehension) -> bool:
    init = ce.accu_init
    if ce.accu_var != MACRO_ACCUMULATOR:
        return False
    if init.WhichOneof("expr_kind") == "list_expr":
        return not init.list_expr.elements
    kind = init.const_expr.WhichOneof("constant_kind") if init.WhichOneof("expr_kind") == "const_expr" else None
    return kind == "bool_value" or (kind == "int64_value" and init.const_expr.int64_value == 0)


class Walk:
    """One walk of one expression: what each node gave for the bindings of the names free in it, and `steps`, the
    nodes walked (a work unit). Nodes are told apart by the parser's ids, unique within an expression."""

    def __init__(self) -> None:
        self.steps = 0
        self._seen: dict[tuple[int, tuple[tuple[str, Reach], ...]], Reach] = {}
        self._free: dict[int, frozenset[str]] = {}

    def reach(self, root: Expr) -> Reach:
        return self._reach(root, {})

    def free(self, e: Expr) -> frozenset[str]:
        """The identifiers `e` reads that it doesn't bind itself: a comprehension binds its variables."""
        found = self._free.get(e.id)
        if found is not None:
            return found
        kind = e.WhichOneof("expr_kind")
        if kind == "ident_expr":
            found = frozenset({e.ident_expr.name})
        elif kind == "comprehension_expr":
            ce = e.comprehension_expr
            body = (self.free(ce.loop_condition) | self.free(ce.loop_step)) - {ce.iter_var, ce.iter_var2, ce.accu_var}
            found = self.free(ce.iter_range) | self.free(ce.accu_init) | body | (self.free(ce.result) - {ce.accu_var})
        else:
            found = frozenset().union(*(self.free(c) for c in children(e)))
        self._free[e.id] = found
        return found

    def _reach(self, e: Expr, scope: dict[str, Reach]) -> Reach:
        bound = tuple(sorted((n, scope[n]) for n in self.free(e) if n in scope))
        found = self._seen.get((e.id, bound))
        if found is None:
            self.steps += 1
            found = self._walk(e, scope)
            self._seen[(e.id, bound)] = found
        return found

    def _walk(self, e: Expr, scope: dict[str, Reach]) -> Reach:
        kind = e.WhichOneof("expr_kind")
        if kind == "const_expr":
            return WHOLE
        if kind == "ident_expr":
            return scope.get(e.ident_expr.name, NONE)  # a global is run data
        if kind == "select_expr":
            if e.select_expr.test_only:
                return NONE
            return _below(self._reach(e.select_expr.operand, scope), e.select_expr.field)
        if kind == "list_expr":
            if not e.list_expr.elements:
                return WHOLE  # written empty (a macro's empty start is never walked)
            return frozenset((i, *p) for i, x in enumerate(e.list_expr.elements) for p in self._reach(x, scope))
        if kind == "struct_expr":
            return self._struct(e.struct_expr, scope)
        if kind == "call_expr":
            return self._call(e, scope)
        if kind == "comprehension_expr":
            return self._comprehension(e.comprehension_expr, scope)
        return NONE

    def _struct(self, s: Expr.CreateStruct, scope: dict[str, Reach]) -> Reach:
        if not s.entries:
            return frozenset({(), (Wild.KEY,)})  # written empty: its value, and its (no) keys where keys are marked
        if s.message_name:  # a message: its fields aren't its JSON's keys (a Struct's `fields` are)
            return ANYWHERE if any(self._reach(entry.value, scope) for entry in s.entries) else NONE
        out: set[Position] = set()
        for entry in s.entries:
            if self._reach(entry.map_key, scope):
                out.add((Wild.KEY,))
            fixed = _key(entry.map_key)
            out |= {(fixed if isinstance(fixed, str) else Wild.VALUE, *p) for p in self._reach(entry.value, scope)}
        return frozenset(out)

    def _call(self, e: Expr, scope: dict[str, Reach]) -> Reach:
        function, args = e.call_expr.function, operands(e)
        if function in STOPS:
            return NONE
        if function == "_?_:_" and len(args) == 3:
            return self._reach(args[1], scope) | self._reach(args[2], scope)
        if function == "_[_]" and len(args) == 2:
            return _below(self._reach(args[0], scope), _key(args[1]))
        if function in _ARITHMETIC:
            return _flat(frozenset().union(*(self._reach(x, scope) for x in args if not _empty(x))))
        if function in _SCALAR and args:
            return WHOLE if self._reach(args[0], scope) else NONE
        if function in ("dyn", "asList") and len(args) == 1:
            return self._reach(args[0], scope)
        if function == "sortedKeys" and len(args) == 1:
            keys = self._reach(args[0], scope)
            return ANYWHERE if any(p and p[0] is Wild.ANY for p in keys) else ELEMENTS if (Wild.KEY,) in keys else NONE
        return ANYWHERE if any(self._reach(x, scope) for x in args) else NONE  # unknown: anywhere

    def _comprehension(self, ce: Expr.Comprehension, scope: dict[str, Reach]) -> Reach:
        source = self._reach(ce.iter_range, scope)
        bound = {ce.iter_var: _elements(source)}
        if ce.iter_var2:  # no macro of this runtime writes one: both variables, anywhere
            bound = {ce.iter_var: ANYWHERE if source else NONE, ce.iter_var2: ANYWHERE if source else NONE}
        accu = NONE if _macro_start(ce) else self._reach(ce.accu_init, scope)
        for _ in range(_ROUNDS):
            grown = accu | self._reach(ce.loop_step, {**scope, **bound, ce.accu_var: accu})
            if grown == accu:
                break
            accu = grown
        else:
            accu = ANYWHERE if accu else NONE
        return self._reach(ce.result, {**scope, ce.accu_var: accu})
