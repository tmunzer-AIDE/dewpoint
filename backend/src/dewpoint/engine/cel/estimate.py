# SPDX-License-Identifier: Apache-2.0
"""Static bound estimator (spec §5.5, rule 4): worst-case iterations, memory and work, assuming every referenced
input is at the runtime caps. Sizes use caps.model_size.

*Memory* is the largest intermediate value plus what the runtime *retains*: every accumulator copy a map or filter
makes (caps.ACCUMULATOR_SLOT), which lives until the evaluation ends, so a chain's copies add up.

*Work* counts node evaluations (a comprehension body once per iteration), plus what a call costs by the size of what
it reads, at rates measured against a native node: Python-implemented fn-1 calls and the values they convert, text
copied or compared, lists and maps compared node by node, substring search (text x needle) and regular expressions
(text x pattern). Iterations alone don't bound CPU: a body can call a Python function hundreds of times per element,
or copy a 16 KiB string. Text from the inputs is at most a string at the cap per reference, and at most the inputs'
JSON over a whole range. The yield policy sums work (route.py).

A value's bound has three parts: a constant, a multiple of the current comprehension element's size
(`l.map(e, e.name)` stays near the size of `l`), and the *input mass* it may contain. All referenced inputs together
are capped, so distinct input references share one budget: `trigger.a + trigger.b` is at most one input's worth,
while `s + s` counts `s` twice (references on one path of the input tree overlap). Anything without a rule here isn't
local: the allow-list and the estimator are the same table."""

import re
from dataclasses import dataclass, field

from dewpoint.engine.cel import ast, caps
from dewpoint.engine.cel.proto import checked_pb2, syntax_pb2

MAX_REGEX_CODE_POINTS = 256
# Work rates, relative to a native node (~15-35 ns measured). Gate 7 runs the worst case of each against the CPU
# target of a workflow task.
FN_WORK = 15  # a Python-implemented fn-1 call
TEXT_BYTES_PER_WORK = 64  # text copied or read: concatenation, size, conversions, comparisons (<= 0.7 ns a byte)
VALUE_BYTES_PER_WORK = 16  # a value walked node by node: list and map equality, conversion for Python (~1.3 ns a byte)
SEARCH_PAIRS_PER_WORK = 2048  # `contains` may compare every needle byte at every text position (~19 ps a pair)
REGEX_BYTE_POINTS_PER_WORK = 4  # RE2, plain patterns: ~9 ns a text byte per pattern code point, ~19 on short texts
_REGEX_ESCAPES = frozenset("dDsSwWbBAznrtfv")  # besides escaped punctuation
_REGEX_COUNT = re.compile(r"\{([0-9]+)(,([0-9]*))?\}")
_FIXED_ZONE = re.compile(r"UTC|[+-][0-9]{2}:[0-9]{2}")
_NUM = ("int64", "uint64", "double")
_ORDERED = (*_NUM, "bool", "string", "bytes", "duration", "timestamp")
_CMP = ("less", "less_equals", "greater", "greater_equals")
_TIME_PARTS = (
    "year", "month", "day_of_year", "day_of_month", "day_of_month_1_based", "day_of_week",
    "hours", "minutes", "seconds", "milliseconds",
)  # fmt: skip

SCALAR = frozenset(
    {
        *(f"{op}_{t}" for op in ("add", "subtract", "multiply", "divide") for t in _NUM),
        "modulo_int64", "modulo_uint64", "negate_int64", "negate_double",
        "add_duration_duration", "add_duration_timestamp", "add_timestamp_duration",
        "subtract_duration_duration", "subtract_timestamp_duration", "subtract_timestamp_timestamp",
        *(f"{op}_{t}" for op in _CMP for t in _ORDERED),
        *(f"{op}_{a}_{b}" for op in _CMP for a in _NUM for b in _NUM if a != b),
        "equals", "not_equals", "logical_and", "logical_or", "logical_not", "not_strictly_false", "in_list", "in_map",
        "size_string", "size_bytes", "size_list", "size_map", "string_size", "bytes_size", "list_size", "map_size",
        "int64_to_int64", "uint64_to_int64", "double_to_int64", "string_to_int64", "timestamp_to_int64",
        "duration_to_int64", "double_to_double", "int64_to_double", "uint64_to_double", "string_to_double",
        "uint64_to_uint64", "int64_to_uint64", "double_to_uint64", "string_to_uint64", "bool_to_bool",
        "string_to_bool", "timestamp_to_timestamp", "string_to_timestamp", "int64_to_timestamp",
        "duration_to_duration", "string_to_duration", "int64_to_duration",
        "contains_string", "starts_with_string", "ends_with_string", "type",
        *(f"timestamp_to_{part}" for part in _TIME_PARTS),
        *(f"duration_to_{part}" for part in ("hours", "minutes", "seconds", "milliseconds")),
        "ipInCidr_string_string", "cidrContains_string_string",
    }
)  # fmt: skip
ZONED = frozenset(f"timestamp_to_{part}_with_tz" for part in _TIME_PARTS)
REGEX = frozenset({"matches", "matches_string"})
SUM = frozenset({"add_string", "add_bytes", "add_list"})
SAME = frozenset({"string_to_string", "bytes_to_bytes", "string_to_bytes", "bytes_to_string", "to_dyn", "asList_list"})
SAME_COUNT = frozenset({"sortedKeys_map"})  # a list with the map's entry count, no bigger than the map
ELEMENT = frozenset({"index_list", "index_map"})
SHORT_STRING = {
    "int64_to_string": 32, "uint64_to_string": 32, "double_to_string": 32, "bool_to_string": 8,
    "timestamp_to_string": 40, "duration_to_string": 40, "macNormalize_string": 12, "macOui_string": 6,
}  # fmt: skip
LOCAL_OVERLOADS = SCALAR | ZONED | REGEX | SUM | SAME | SAME_COUNT | ELEMENT | {"conditional", *SHORT_STRING}
# Implemented in Python (functions.py): each call crosses into the interpreter and converts its arguments.
FN_TEXT = frozenset({"ipInCidr_string_string", "cidrContains_string_string", "macNormalize_string", "macOui_string"})
FN_VALUE = frozenset({"sortedKeys_map", "asList_list"})
TEXT_READ = frozenset(
    {
        "add_string", "add_bytes", "size_string", "string_size", "string_to_bytes", "bytes_to_string",
        "string_to_int64", "string_to_uint64", "string_to_double", "string_to_bool", "string_to_timestamp",
        "string_to_duration", "starts_with_string", "ends_with_string",
        *(f"{op}_{t}" for op in _CMP for t in ("string", "bytes")),
    }
)  # fmt: skip
KEY_READ = {"in_map": 0, "index_map": 1}  # the operand holding the key, which is hashed


class NotLocal(Exception):
    """The expression is outside the proven subset; `reason` is shown in the editor."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


COUNT = max(caps.LIST_LENGTH, caps.MAP_ENTRIES)


def _union(a: tuple[ast.Path, ...], b: tuple[ast.Path, ...]) -> tuple[ast.Path, ...]:
    """Multiset union (max of multiplicities): the value is one of two alternatives."""
    out = list(a)
    for path in set(b):
        out += [path] * max(0, b.count(path) - a.count(path))
    return tuple(sorted(out))


def overlap(refs: tuple[ast.Path, ...]) -> int:
    """How many times the input mass can be counted: the most references on one root-to-leaf path."""
    return max((sum(1 for o in refs if o[: len(r)] == r or r[: len(o)] == o) for r in refs), default=0)


@dataclass(frozen=True)
class Est:
    const: int
    coef: int = 0  # multiplies the current comprehension element's size
    count: int = 0  # element bound of a list or map
    refs: tuple[ast.Path, ...] = ()  # input chains whose mass the value may contain (a multiset, sorted)

    def join(self, other: "Est") -> "Est":
        return Est(
            max(self.const, other.const),
            max(self.coef, other.coef),
            max(self.count, other.count),
            _union(self.refs, other.refs),
        )

    def bytes(self, element: int) -> int:
        return self.const + self.coef * element + overlap(self.refs) * caps.INPUT_MODEL_BYTES


def _sum(parts: list[Est], extra: int = 0, count: int | None = None) -> Est:
    return Est(
        extra + sum(p.const for p in parts),
        sum(p.coef for p in parts),
        sum(p.count for p in parts) if count is None else count,
        tuple(sorted(r for p in parts for r in p.refs)),
    )


SCALAR_EST = Est(caps.SCALAR)
INPUT_STRING = Est(caps.SCALAR + caps.STRING_BYTES)
SEARCH_NEEDLE_FLOOR = SEARCH_PAIRS_PER_WORK // TEXT_BYTES_PER_WORK  # a short needle still costs one pass of the text
ELEMENT_EST = Est(0, 1, COUNT)


@dataclass(frozen=True)
class Bounds:
    iterations: int
    bytes: int  # the largest intermediate value plus `retained`
    work: int
    retained: int = 0  # accumulator copies the runtime keeps until the evaluation ends


@dataclass
class _Run:
    checked: checked_pb2.CheckedExpr
    iterations: int = 0
    peak: int = 0
    retained: int = 0
    work: int = 0
    repeat: int = 1  # how many times the node being estimated runs (a comprehension body: once per iteration)
    element: int = 0  # size bound of the current comprehension element (0 outside comprehensions)
    element_text: int = 0  # text in all of the current range's elements together
    keyed: tuple[ast.Path, str] | None = None  # inside `sortedKeys(m).…(k, …)`: m's chain and k
    seen: dict[int, Est] = field(default_factory=dict)

    def note(self, e: ast.Expr, est: Est) -> Est:
        self.seen[e.id] = est
        self.peak = max(self.peak, est.bytes(self.element))
        self.work += self.repeat
        return est

    def value(self, e: ast.Expr, local: dict[str, Est]) -> Est:
        kind = e.WhichOneof("expr_kind")
        if kind == "const_expr":
            which = e.const_expr.WhichOneof("constant_kind")
            if which == "string_value":
                return self.note(e, Est(caps.SCALAR + len(e.const_expr.string_value.encode())))
            if which == "bytes_value":
                return self.note(e, Est(caps.SCALAR + len(e.const_expr.bytes_value)))
            return self.note(e, SCALAR_EST)
        if kind == "ident_expr" and e.ident_expr.name in local:
            return self.note(e, local[e.ident_expr.name])
        if kind in ("ident_expr", "select_expr") and not (kind == "select_expr" and e.select_expr.test_only):
            path = ast.chain_path(e, frozenset(local))
            if path is not None:
                return self.note(e, self._input(e, path))
        if kind == "select_expr":
            operand = self.value(e.select_expr.operand, local)
            if e.select_expr.test_only:
                return self.note(e, SCALAR_EST)
            return self.note(e, Est(operand.const, operand.coef, COUNT, operand.refs))
        if kind == "list_expr":
            items = [self.value(x, local) for x in e.list_expr.elements]
            return self.note(e, _sum(items, caps.SCALAR, len(items)))
        if kind == "struct_expr":
            if e.struct_expr.message_name:
                raise NotLocal("builds a message")
            parts = [self.value(x, local) for x in ast.children(e)]
            return self.note(e, _sum(parts, caps.SCALAR, len(e.struct_expr.entries)))
        if kind == "call_expr":
            return self.note(e, self._call(e, local))
        if kind == "comprehension_expr":
            return self.note(e, self._comprehension(e, local))
        raise NotLocal("uses an unsupported construct")

    def _input(self, e: ast.Expr, path: ast.Path) -> Est:
        """A referenced input, or part of one."""
        t = self.checked.type_map.get(e.id)
        if t is not None and t.WhichOneof("type_kind") == "primitive":
            return INPUT_STRING if t.primitive == 5 else SCALAR_EST  # 5: STRING
        return Est(0, 0, COUNT, (path,))

    def _call(self, e: ast.Expr, local: dict[str, Est]) -> Est:
        ids = ast.overloads(self.checked, e.id)
        name = e.call_expr.function
        if not ids or any(i not in LOCAL_OVERLOADS for i in ids):
            raise NotLocal(f"`{name}` doesn't run inline")
        ops = ast.operands(e)
        if REGEX & set(ids):
            _literal(ops[-1], MAX_REGEX_CODE_POINTS, None, "a regular expression that isn't a short literal")
            if not _plain_regex(ops[-1].const_expr.string_value):
                raise NotLocal("a regular expression with (?) groups or unsupported escapes")
        if ZONED & set(ids):
            _literal(ops[-1], 64, _FIXED_ZONE, "a named time zone (only UTC and fixed offsets run inline)")
        args = [self.value(op, local) for op in ops]
        self.work += max(self._charge(i, ops, args) for i in ids)  # whichever overload runs
        if self.keyed is not None and set(ids) <= ELEMENT and len(ops) == 2:
            chain, key = self.keyed
            if ast.chain_path(ops[0], frozenset(local)) == chain and _is_ident(ops[1], key):
                return ELEMENT_EST  # m[k] over sortedKeys(m): distinct keys, so the values sum to at most m
        out = self._rule(ids[0], args)
        for overload in ids[1:]:
            out = out.join(self._rule(overload, args))
        return out

    def _value(self, x: Est) -> int:
        """Model bytes a call reads from `x` over the run: its own part once per run of the node, its element part
        summed over the range."""
        return self.repeat * (x.const + overlap(x.refs) * caps.INPUT_MODEL_BYTES) + x.coef * self.element

    def _text_once(self, x: Est) -> int:
        """Text bytes `x` holds in one run of the node, when it is a string or bytes."""
        inputs = min(len(x.refs) * INPUT_STRING.const, overlap(x.refs) * caps.TOTAL_JSON)
        return x.const + inputs + x.coef * min(self.element_text, INPUT_STRING.const)

    def _text(self, x: Est) -> int:
        """Text bytes a call reads from `x` over the run (as `_value`, for strings and bytes)."""
        inputs = min(len(x.refs) * INPUT_STRING.const, overlap(x.refs) * caps.TOTAL_JSON)
        return self.repeat * (x.const + inputs) + x.coef * self.element_text

    def _charge(self, overload: str, ops: list[ast.Expr], args: list[Est]) -> int:
        """What a call costs beyond its own node, by the size of what it reads."""
        if overload in FN_TEXT:
            return self.repeat * FN_WORK + sum(map(self._text, args)) // TEXT_BYTES_PER_WORK
        if overload in FN_VALUE:
            converted = sum(map(self._value, args)) // VALUE_BYTES_PER_WORK
            return self.repeat * (FN_WORK + args[0].count) + converted
        if overload in TEXT_READ:
            return sum(map(self._text, args)) // TEXT_BYTES_PER_WORK
        if overload in KEY_READ:
            return self._text(args[KEY_READ[overload]]) // TEXT_BYTES_PER_WORK
        if overload in ("equals", "not_equals"):  # node by node, stopping at the smaller value
            return min(map(self._value, args)) // VALUE_BYTES_PER_WORK
        if overload == "in_list":
            return self._value(args[1]) // VALUE_BYTES_PER_WORK
        if overload == "add_list":
            return self.repeat * sum(a.count for a in args)
        if overload == "contains_string":
            needle = max(self._text_once(args[1]), SEARCH_NEEDLE_FLOOR)
            return self._text(args[0]) * needle // SEARCH_PAIRS_PER_WORK
        if overload in REGEX:
            points = _regex_points(ops[-1].const_expr.string_value)
            return self._text(args[0]) * points // REGEX_BYTE_POINTS_PER_WORK
        return 0

    def _rule(self, overload: str, args: list[Est]) -> Est:
        if overload in SUM:
            return _sum(args)
        if overload in SAME or overload in SAME_COUNT:
            return args[0]
        if overload in ELEMENT:
            return Est(args[0].const, args[0].coef, COUNT, args[0].refs)
        if overload == "conditional":
            return args[1].join(args[2])
        if overload in SHORT_STRING:
            return Est(caps.SCALAR + SHORT_STRING[overload])
        return SCALAR_EST

    def _comprehension(self, e: ast.Expr, local: dict[str, Est]) -> Est:
        ce = e.comprehension_expr
        if self.element:
            raise NotLocal("more than one nested loop")
        source = self.value(ce.iter_range, local)
        if source.coef:
            raise NotLocal("more than one nested loop")
        self.iterations += source.count
        start = self.value(ce.accu_init, local)
        self.element = source.bytes(0)  # every element is no bigger than the list holding it
        self.element_text = source.const + overlap(source.refs) * caps.TOTAL_JSON
        self.keyed = _keyed(ce, self.checked, frozenset(local))
        self.repeat = source.count
        body = {**local, ce.iter_var: ELEMENT_EST, ce.accu_var: start}
        self.value(ce.loop_condition, body)
        self.value(ce.loop_step, body)
        self.repeat = 1
        appended = _appended(ce)
        if appended is None:
            result = SCALAR_EST
        else:
            x = self.seen[appended]
            repeated = source.count * (x.const + overlap(x.refs) * caps.INPUT_MODEL_BYTES)
            result = Est(start.const + repeated + x.coef * source.const, 0, source.count, source.refs * x.coef)
            self.retained += caps.ACCUMULATOR_SLOT * source.count * (source.count + 1) // 2
        self.element, self.element_text, self.keyed = 0, 0, None
        self.peak = max(self.peak, result.bytes(0))
        return self.value(ce.result, {**local, ce.accu_var: result})


def _literal(e: ast.Expr, limit: int, pattern: re.Pattern[str] | None, reason: str) -> None:
    ok = e.WhichOneof("expr_kind") == "const_expr" and e.const_expr.WhichOneof("constant_kind") == "string_value"
    text = e.const_expr.string_value if ok else ""
    if not ok or len(text) > limit or (pattern is not None and not pattern.fullmatch(text)):
        raise NotLocal(reason)


def _plain_regex(pattern: str) -> bool:
    """No `(?` groups (flags, names) or letter escapes beyond \\d \\s \\w \\b \\A \\z and control characters (Unicode
    classes, code points): RE2's compiled size then follows the pattern written out, which the work charge assumes."""
    escapes = pattern.split("\\")[1:]
    return "(?" not in pattern and all(
        e[:1] and (e[0] in _REGEX_ESCAPES or (e[0].isascii() and not e[0].isalnum())) for e in escapes
    )


def _regex_points(pattern: str) -> int:
    """The pattern's length with every `{n,m}` count written out: a count copies the atom before it (a character,
    escape, class or group) n or m times, `{n,}` once more for its star."""
    levels: list[list[int]] = [[]]  # atom sizes, per open group
    i = 0
    while i < len(pattern):
        count = _REGEX_COUNT.match(pattern, i)
        if count and levels[-1]:
            low, comma, high = count.groups()
            copies = max(1, int(high) if high else int(low) + 1 if comma else int(low))
            levels[-1][-1] = levels[-1][-1] * copies + len(count.group())
            i = count.end()
        elif pattern[i] == "(":
            levels.append([])
            i += 1
        elif pattern[i] == ")" and len(levels) > 1:
            group = levels.pop()
            levels[-1].append(sum(group) + 2)
            i += 1
        else:
            end = i + 2 if pattern[i] == "\\" else _class_end(pattern, i) if pattern[i] == "[" else i + 1
            levels[-1].append(end - i)
            i = end
    return sum(map(sum, levels)) + len(levels) - 1  # an unclosed group's "(" counts too


def _class_end(pattern: str, i: int) -> int:
    """Just past the character class opening at `i` (a leading ] or ^] is literal; [:alpha:] is one member)."""
    j = i + 1 + pattern.startswith("^", i + 1)
    j += pattern.startswith("]", j)
    while j < len(pattern) and pattern[j] != "]":
        posix = pattern.find(":]", j + 2) if pattern.startswith("[:", j) else -1
        j = posix + 2 if posix >= 0 else j + 2 if pattern[j] == "\\" else j + 1
    return j + 1


def _is_ident(e: ast.Expr, name: str) -> bool:
    return e.WhichOneof("expr_kind") == "ident_expr" and bool(e.ident_expr.name == name)


def _keyed(
    ce: syntax_pb2.Expr.Comprehension, checked: checked_pb2.CheckedExpr, scope: frozenset[str]
) -> tuple[ast.Path, str] | None:
    """For a comprehension over `sortedKeys(<chain>)`: the chain and the iteration variable."""
    rng = ce.iter_range
    if rng.WhichOneof("expr_kind") != "call_expr" or ast.overloads(checked, rng.id) != ("sortedKeys_map",):
        return None
    path = ast.chain_path(rng.call_expr.args[0], scope)
    return (path, ce.iter_var) if path is not None else None


def _appended(ce: syntax_pb2.Expr.Comprehension) -> int | None:
    """The id of `x` in the macro's own accumulator append `accu + [x]` (map and filter), or None."""
    for node in ast.walk(ce.loop_step):
        if node.WhichOneof("expr_kind") != "call_expr" or node.call_expr.function != "_+_":
            continue
        args = node.call_expr.args
        if (
            len(args) == 2
            and args[0].WhichOneof("expr_kind") == "ident_expr"
            and args[0].ident_expr.name == ce.accu_var
            and args[1].WhichOneof("expr_kind") == "list_expr"
            and len(args[1].list_expr.elements) == 1
        ):
            return int(args[1].list_expr.elements[0].id)
    return None


def estimate(checked: checked_pb2.CheckedExpr) -> Bounds:
    """Raises NotLocal when the expression is outside the allow-list."""
    run = _Run(checked)
    run.value(checked.expr, {})
    return Bounds(run.iterations, run.peak + run.retained, run.work, run.retained)
