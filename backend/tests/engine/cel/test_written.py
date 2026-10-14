# SPDX-License-Identifier: Apache-2.0
"""Where the constants written into a CEL expression may land in its value (engine 2b spec §3.8, issue #79): publish
refuses one that lands at a part a schema marks sensitive, as it refuses the same constant written as a literal."""

import pytest

from dewpoint.engine.cel import ast, written
from dewpoint.engine.cel import runtime as cel_runtime
from dewpoint.engine.cel.written import Position, Wild

SECRET = '"s3cr3t-value"'
ITEM, VALUE, KEY, ANY = Wild.ITEM, Wild.VALUE, Wild.KEY, Wild.ANY


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        # every constant the author writes, empty or not
        (SECRET, {()}), ("null", {()}), ("true", {()}), ("-5", {()}), ('b"x"', {()}), ('""', {()}),
        ("trigger.tok", set()), (".trigger.tok", set()),
        # beside a read, but empty text, bytes or list joined by `+` writes nothing
        (f"{SECRET} + trigger.tok", {()}), ('"" + trigger.tok', set()), ('b"" + trigger.b', set()),
        ("[] + trigger.strs", set()), ("trigger.strs + []", set()),
        # a condition's branches carry, never its condition
        (f'trigger.n > 0 ? {SECRET} : ""', {()}), (f"{SECRET} == trigger.tok ? trigger.a : trigger.b", set()),
        ('has(trigger.tok) ? trigger.tok : ""', {()}), ("has(trigger.tok) ? trigger.tok : null", {()}),
        # arithmetic and conversions carry; a getter carries its receiver, never its time zone
        ("trigger.n + 1", {()}), ("-trigger.n", set()), ("string(4242)", {()}),
        ('timestamp("2020-01-01T00:00:00Z").getHours("+05:00")', {()}), ('trigger.t.getHours("+05:00")', set()),
        ('macNormalize("aa:bb:cc:dd:ee:ff")', {()}), (f"dyn({SECRET})", {()}),
        # a boolean, a count or a type carries nothing
        (f"size({SECRET})", set()), ('"a" in trigger.l', set()), ("has(trigger.x)", set()),
        (f'has({{"a": {SECRET}}}.a)', set()),
        ('trigger.tok.startsWith("ab")', set()), ('type("x") == type(trigger.x)', set()),
        ('ipInCidr(trigger.ip, "10.0.0.0/8")', set()),
        # a lookup's key or index carries nothing, and a constant one is followed
        ('trigger.headers["Authorization"]', set()), ("trigger.toks[0]", set()),
        (f"[{SECRET}, trigger.x][0]", {()}), (f"[{SECRET}, trigger.x][1]", set()),
        (f"[{SECRET}, trigger.x][0u]", {()}), (f"[{SECRET}, trigger.x][1u]", set()),
        # positions: a map's constant keys and a list's indexes as written; any element of a list (`ITEM`) or any
        # value of a map (`VALUE`) where the walk can't tell which (the fresh review's Medium: the rest is kept)
        ('{"ssid": "corp", "passphrase": trigger.psk}', {(KEY,), ("ssid",)}),
        (f"{{trigger.k: {SECRET}}}", {(VALUE,)}), ('["a", trigger.x]', {(0,)}), ('["a"] + trigger.l', {(ITEM,)}),
        ('[{"name": "a"}] + trigger.l', {(ITEM, "name"), (ITEM, KEY)}),
        (f'{{"a": {SECRET}}}.a', {()}), (f'{{"a": {SECRET}}}[trigger.k]', {()}), (f'{{"a": [{SECRET}]}}.b', set()),
        (f"sortedKeys({{{SECRET}: 1}})", {(ITEM,)}), (f"asList([{SECRET}])", {(0,)}),
        # a key computed from a constant is written all the same
        ('{"k3y-" + trigger.k: trigger.v}', {(KEY,)}), ('["k3y-value"].map(k, {k: trigger.v})[0]', {(KEY,)}),
        # a comprehension's variables, even named as a root; a macro's own start isn't the author's
        (f"[{SECRET}].map(x, x)[0] + trigger.y", {()}), (f"{{{SECRET}: 1}}.map(k, k)", {(ITEM,)}),
        ("trigger.l.map(x, x + 1)", {(ITEM,)}), ("trigger.l.filter(x, x > 0)", set()),
        ("trigger.l.all(x, x > 0)", set()), ("trigger.l.exists(x, x > 0)", set()),
        ("trigger.l.exists_one(x, x > 0)", set()), (f"[{SECRET}].map(trigger, trigger)", {(ITEM,)}),
        ('trigger.lst.map(x, {"name": "corp-" + x.name, "psk": x.psk})', {(ITEM, "name"), (ITEM, KEY)}),
        # a function the tables don't name, or a message, carries everything anywhere (the fresh review's High:
        # a Struct's `fields` are the object's own keys)
        (f"unknownFn(trigger.x, {SECRET})", {(ANY,)}),
        (f"google.protobuf.Struct{{fields: {{{SECRET}: trigger.tok}}}}", {(ANY,)}),
        ('google.protobuf.Value{struct_value: {"k": trigger.v}}', {(ANY,)}),
        ("google.protobuf.Struct{fields: {trigger.k: trigger.v}}", set()),
        # written empties (the owner's first plan review); containers of reads write nothing
        ("trigger.flag ? [] : trigger.lst", {()}), ("trigger.flag ? {} : trigger.obj", {(), (KEY,)}),
        ("google.protobuf.Struct{}", {(), (KEY,)}),
        ("[trigger.a, trigger.b]", set()), ("{trigger.k: trigger.v}", set()), ("trigger.l.map(x, x)", set()),
        (f"{{trigger.k: {SECRET}}}.map(k, k)", set()),  # iterating a map binds its keys, never its values
        # keys stay keys where the index is lost (the owner's second plan review) ...
        ('[{"pw": trigger.pw}] + [{"pw": trigger.pw}]', {(ITEM, KEY)}),
        ('trigger.lst.map(x, {"pw": trigger.pw})', {(ITEM, KEY)}),
        ('[{"pw": trigger.pw}].filter(x, true)', {(ITEM, KEY)}),
        ('{trigger.k: {"pw": trigger.pw}}', {(VALUE, KEY)}), ('[{"pw": trigger.pw}][trigger.i]', {(KEY,)}),
        ('trigger.lst.map(x, {"pw": trigger.pw})[0]', {(KEY,)}),
        ('([{"pw": trigger.pw}] + trigger.l).map(y, y)', {(ITEM, KEY)}),
        # ... and become values where their own map is iterated, or sortedKeys reads them
        (f'["x"].map(i, {{{SECRET}: trigger.v}})[0].map(k, k)', {(ITEM,)}),
        (f"{{{SECRET}: trigger.v}}.map(k, k)", {(ITEM,)}),
        (f"sortedKeys([{{{SECRET}: trigger.v}}][0])", {(ITEM,)}),
        ('sortedKeys(trigger.lst.map(x, {"pw": trigger.pw})[0])', {(ITEM,)}),
        ('sortedKeys(trigger.lst.map(x, {"pw": trigger.pw}))', set()),  # a list's elements' keys aren't its keys
    ],
)  # fmt: skip
def test_where_a_written_constant_lands(expr: str, expected: set[Position]) -> None:
    assert set(written.reaching(cel_runtime.parse(expr).expr)) == expected


# Every call the validator's environment declares (cel-expr-python 0.1.3's standard library and fn-1, probed by
# compiling): each is classified, so the default for a function the tables don't name applies only outside it.
DECLARED = (
    "_+_", "_-_", "_*_", "_/_", "_%_", "-_", "_==_", "_!=_", "_<_", "_<=_", "_>_", "_>=_", "_&&_", "_||_", "!_",
    "_?_:_", "_[_]", "@in", "@not_strictly_false", "size", "contains", "startsWith", "endsWith", "matches", "type",
    "dyn", "int", "uint", "double", "string", "bytes", "bool", "timestamp", "duration", "getFullYear", "getMonth",
    "getDayOfYear", "getDayOfMonth", "getDate", "getDayOfWeek", "getHours", "getMinutes", "getSeconds",
    "getMilliseconds", "sortedKeys", "asList", "ipInCidr", "cidrContains", "macNormalize", "macOui",
)  # fmt: skip


def test_every_declared_call_is_classified_once() -> None:
    assert [f for f in DECLARED if (f in written.CARRIES) == (f in written.STOPS)] == []
    assert written.CARRIES | written.STOPS == set(DECLARED)


def renumbered(e: ast.Expr) -> ast.Expr:
    """A hand-built AST's node ids made unique again, as a parser makes them (the walk remembers nodes by id)."""
    for i, node in enumerate(ast.walk(e), start=1):
        node.id = i
    return e


def test_a_second_comprehension_variable_is_bound_anywhere() -> None:
    """The protos carry `iter_var2`; no macro of this runtime writes one, so a comprehension that has one binds both
    variables to anything its range holds, anywhere."""
    parsed = cel_runtime.parse(f"[{SECRET}].map(x, y)")
    assert set(written.reaching(parsed.expr)) == set()  # `y` is run data here
    parsed.expr.comprehension_expr.iter_var2 = "y"
    assert set(written.reaching(parsed.expr)) == {(ITEM, ANY)}


def test_an_accumulator_that_never_settles_is_anywhere() -> None:
    """No macro of this runtime grows its accumulator's positions past two rounds; a comprehension that would (its
    step nesting the accumulator deeper each round) is read as anything anywhere."""
    e = cel_runtime.parse("[1].map(x, x)").expr
    ce = e.comprehension_expr
    ce.accu_var = "acc"
    ce.accu_init.CopyFrom(cel_runtime.parse(SECRET).expr)
    ce.loop_step.CopyFrom(cel_runtime.parse("[acc]").expr)
    ce.result.CopyFrom(cel_runtime.parse("acc").expr)
    assert set(written.reaching(renumbered(e))) == {(ANY,)}


def test_nested_macros_are_walked_in_work_linear_in_their_size() -> None:
    """The fresh review's Medium: each comprehension walks its step until its accumulator settles, so nested macros
    cost 2^depth walks without remembering what a node gave for the same bindings. Counted in nodes walked, not time:
    eight chains of twelve nested maps."""
    chain = '"s"'
    for depth in range(12):
        chain = f"[1].map(v{depth}, {chain})"
    parsed = cel_runtime.parse(f"[{', '.join([chain] * 8)}, [trigger.tok]]")
    nodes = sum(1 for _ in ast.walk(parsed.expr))
    walk = written.Walk()
    assert walk.reach(parsed.expr) == {(i, *(ITEM,) * 12) for i in range(8)}
    assert walk.steps <= 4 * nodes
