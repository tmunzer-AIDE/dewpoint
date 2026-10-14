# A constant a formula carries into a sensitive position (issue #79)

Branch `fix/cel-literal-sensitive` from `origin/main` b61ede43, fast-forwarded to 52314866 (#99, Engine ABI 8 and the
patched runtime `cel-expr-python 0.1.3+dewpoint.1`) before any commit, on the owner's choice of #79 (2026-10-14). A plan for
the owner's rulings; nothing is built until the owner's go, and nothing is committed without it. Executed inline
(memory: inline execution with milestone reviews): the checkpoint is after the fresh review.

**Goal:** publish refuses a CEL expression at a sensitive position when a constant written in it can land at a part
the target marks, as it refuses the same constant written as a literal, a template's text or a reference's default.

**Architecture:** a walk over the parsed CEL AST (`engine/cel/written.py`, new) answers where the expression's
constants may land in its value; the validator (`_writes_sensitive`, `engine/graph/validate.py`) checks each landing
position against the schema with the rules a literal is checked with (`engine/sensitive.py`, new helpers that navigate
as `is_marked` does). Every check of a value envelope then reads the schema from the config's root through that
navigation, never through `target_schema()`, which can't follow a tuple position or a union's branches (the owner's
plan review). Validator only.

## Facts (checked 2026-10-14 at b61ede43, the runtime's again at 52314866; never from memory)

- The issue's four examples still publish clean at an `x-sensitive` string position (testkit `ambiguous_send`
  `/token`): `"Bearer " + trigger.tok`, `trigger.n > 0 ? "<secret>" : ""`, `has(trigger.x) ? "<secret>" :
  "<secret>"`, `run.id != "" ? "<secret>" : ""`. `"<secret>"` alone is refused (`sensitive.literal`, #76's rule:
  a formula that reads nothing).
- Engine 2b spec §3.8 counts null and the empty string as literals; a template at a sensitive position is refused
  with any non-empty text (a `Bearer ` prefix included: publish can't tell a prefix from a secret) or a default; empty
  text beside a reference writes nothing. A reference's default (even `""` or null) is refused. Its last bullet names
  this gap as "Not covered".
- The validator's CEL environment is cel-expr-python 0.1.3's standard library plus fn-1, nothing else, the same on
  #99's patched `0.1.3+dewpoint.1` (the same 42 of 70 probes accepted, the same call names and macro shapes) (probed by
  compiling: `lowerAscii`, `replace`, `split`, `join`, `format`, `substring`, `trim`, `base64`, `math`, `optional`,
  `lists`, `sets`, `sort`, `cel.bind`, `transformList`/`transformMap` are all undeclared or not macros). The parsed
  AST names its calls: the operators (`_+_`, `_-_`, `_*_`, `_/_`, `_%_`, `-_`, `_==_`, `_!=_`, `_<_`, `_<=_`, `_>_`,
  `_>=_`, `_&&_`, `_||_`, `!_`, `_?_:_`, `_[_]`, `@in`, `@not_strictly_false`), `size`, `contains`, `startsWith`,
  `endsWith`, `matches`, `type`, `dyn`, the conversions (`int`, `uint`, `double`, `string`, `bytes`, `bool`,
  `timestamp`, `duration`), the time getters (`getFullYear`, `getMonth`, `getDayOfYear`, `getDayOfMonth`, `getDate`,
  `getDayOfWeek`, `getHours`, `getMinutes`, `getSeconds`, `getMilliseconds`), and fn-1 (`sortedKeys`, `asList`,
  `ipInCidr`, `cidrContains`, `macNormalize`, `macOui`). `has(x.y)` is a presence test (a select, `test_only`), and
  `-5` is folded to a constant.
- Every comprehension comes from a macro, its accumulator named `@result` (no author can name it) and started as the
  macro writes it: `all` from `true`, `exists` from `false`, `exists_one` from `0`, `map` and `filter` from an empty
  list. `exists_one` adds a constant `1` to its accumulator and ends comparing it with `1`.
- Sensitive positions are mostly nested: `mist.api.write` marks secret-named fields at any depth of its body
  (`tests/plugins/mist/test_api_nodes.py`), curated Mist nodes mark `/body/passphrase` and the like, input and
  variable schemas mark single fields. At `mist.api.write`, `/body/passphrase` and `/body/auth/psk` are marked and
  `/body/ssid` isn't; `{"ssid": trigger.s, "passphrase": "psk-" + trigger.psk}` publishes clean today, as does
  `{"ssid": "corp", "passphrase": trigger.psk}`, which writes nothing sensitive and should stay clean.
- Precedent (#76, d0d18722): validator only, so no `ENGINE_ABI` bump: published versions store its outputs and the
  runtime never re-validates.
- `_writes_sensitive` decides whether a value envelope is checked from `is_marked(root, pointer)` and the
  `target_schema(root, pointer)` it's given. `target_schema()` follows `properties`, `additionalProperties` and
  `items` only, so under a tuple position (`prefixItems`) or inside a union's branches it finds nothing: for a
  variable `x` whose schema is a tuple of `{"pw": SECRET}` objects, or a union whose branch holds `y: {"pw": SECRET}`,
  an envelope at `/x/0` or `/x/y` isn't checked. Reproduced (the owner's plan review, then again here): the literal
  `[{"pw": "lit-value"}]` and `{"y": {"pw": "lit-value"}}` are refused (at `/x/0/pw`, `/x/y/pw`), but at those
  positions a formula that reads nothing (`{"pw": "lit-value"}`), a reference's default holding it and a literal
  envelope holding it all publish clean today. §3.8 says #76's rule covers a tuple position and a union's branch.
- An empty container is written: a literal `[]` at a list marked sensitive whole is refused. `[]` and `{}` in a CEL
  expression are container nodes, not constants (the owner's plan review).
- An object of references at a position marked whole writes no literal (`{"user": ref, "pw": ref}` publishes:
  `test_a_sensitive_object_built_from_references_writes_no_literal`), its keys included. Where a map's keys are
  marked (`propertyNames`), `{"k3y-value": 1}` is refused but `{"k3y-value": ref}` publishes: the literal check skips a
  part made only of references (`_holes_only`), the written key with it.

## What carries a constant into the value (the analysis, for the rulings)

On the parsed AST, a constant carries into the result through: the branches of `?:` (never its condition); `+` (text,
bytes, lists, numbers) and the other arithmetic operators; list and map construction (a map's keys as keys); `dyn`;
the conversions; a time getter's receiver (not its time zone); `asList`; `sortedKeys` (its map's keys);
`macNormalize` and `macOui`; a field read or an index of a value holding one; a comprehension's variables (a list's
elements, a map's keys). It doesn't through: comparisons, `in`, `has()`, `size()`, the logical operators, `contains`,
`startsWith`, `endsWith`, `matches`, `type`, `ipInCidr`, `cidrContains`, nor a key or index used for a lookup. So
`trigger.kind == "api" ? trigger.tok : trigger.other` and `trigger.headers["Authorization"]` carry nothing.

## Proposed rulings

- Ruling 1 (which constants): every constant the author writes counts, as a literal does at a sensitive position
  (§3.8): text, bytes, numbers, booleans and null, empty or not; but empty text or bytes joined by `+` writes nothing,
  as empty text beside a template's reference. An empty list or map the author writes (`[]`, `{}`) is written too, as
  the literal `[]` is (the owner's plan review); a list or map holding reads writes only the constants it holds. A
  macro's own accumulator start (`true`, `false`, `0`, an empty list, for `@result`) isn't the author's - cost if
  wrong: a fallback written into a formula at a sensitive position (`has(trigger.tok) ? trigger.tok : ""`, `... :
  null`, `trigger.flag ? [] : trigger.lst`) is refused, as the same fallback written as a reference's default is today;
  the author guards the step instead.
- Ruling 2 (beside a read): a constant carried beside a read is refused as a template's text is: `"Bearer " +
  trigger.tok` (the owner's ruling for templates, 2026-10-09) - cost if wrong: a prefix comes with the secret (in the
  run's input), as a template's must.
- Ruling 3 (the functions): the table above, closed over this runtime's functions; a function it doesn't name carries
  every constant of its operands anywhere into its result (refused) - cost if wrong: a function a new runtime adds is
  refused at sensitive positions until classified (a new runtime is a new CEL profile behind the §5.9 gates anyway).
- Ruling 4 (where): a constant is refused only where it may land at a part the target marks, by the rules a literal
  is checked with: a list's indexes and a map's constant keys are followed as written; where publish can't follow (list
  concatenation, a map key chosen at run time, a comprehension's elements, an unknown function), the constant may be
  anywhere at or under the last position known; a map's key counts only where the schema marks that map's keys
  (`propertyNames`): never because the map lies at a marked position, nor because the key's value is marked (an object
  of reads there writes no literal, as an object of references doesn't). A key stays a key where the walk loses its
  path (a list concatenated, a macro's elements, a value under a key chosen at run time) and is checked against the
  keys any map there may mark; it becomes a value only where its own map is iterated or `sortedKeys` reads it (the
  owner's second plan review). So `{"ssid": "corp", "passphrase":
  trigger.psk}` publishes at a Mist body, `{"user": trigger.user, "pw": trigger.pw}` at a login marked whole, and
  `{"ssid": trigger.s, "passphrase": "psk-" + trigger.psk}` is refused - cost if wrong: none (a literal object is
  checked part by part already).
- Ruling 5 (unchanged): a formula that reads nothing stays refused wherever the target could mark a part (#76: its
  whole value is fixed, and a fixed value can come from a function that carries nothing, `string(size("…"))`);
  templates and references are unchanged; the diagnostic is the literal's (`sensitive.literal`, the same message,
  never quoting the constant); published versions keep what they hold, and a draft holding such a formula fails
  validate and publish until changed - cost if wrong: none.
- Ruling 6 (the review's Medium, and its siblings): whether and where a value envelope writes at a sensitive part is
  read from the config's root through the schema's own navigation (a tuple position, a union's branches, a pattern,
  `additionalProperties`, a local `$ref`), as a literal written in place is, never through `target_schema()`. A
  formula (reading or not), a reference's default and a literal envelope nested under a tuple position or inside a
  union's branch are checked as the same value written in place: all three fail open today (facts) - cost if wrong:
  none.
- Ruling 7 (a sibling the review led to): a key written in a map whose schema marks its keys counts even when its
  value is a reference: `{"k3y-value": {"$ref": …}}` is refused there as `{"k3y-value": 1}` is; an object made only
  of references at a position marked whole stays allowed (its keys are structure) - cost if wrong: such a map takes
  its keys from run data (a formula with a read key), never written. Separable: it can be split out as its own issue
  instead.

## Not in scope

- §3.8 guards against writing a secret by mistake, not against an author encoding one on purpose through functions
  that carry nothing (lengths, comparisons): `string(size("…"))` publishes.
- A position-by-position check of a formula that reads nothing (ruling 5), and #78 (declassify entries).

## Global constraints

- Test-first, each test watched failing; each protection mutation-checked. `ruff check`, `ruff format`, `ruff check`,
  mypy and the import contracts pass. No `ENGINE_ABI` bump; no migration; no frontend change.
- A diagnostic never quotes a value. No provider credential-shaped literal in a test.
- Commands: the borrowed venv `~/4_dev/mist_dewpoint-celbackport/backend/.venv` (its lock is 52314866's; the
  writebound worktree is gone) with `PYTHONPATH=src` (and `.` for `tests.support`), run from `backend/`.

## Review focus (inputs no rule above names; each pinned by a test in the task that owns it)

1. Formulas an author writes at a sensitive position that carry no constant still publish: a lookup by a constant key
   (`trigger.headers["Authorization"]`), a constant in a condition or a filter's predicate
   (`steps.a.output.items.filter(x, x.kind == "api")[0].token`), an index (`trigger.toks[0]`) - Task 3.
2. A body built by a formula with constants at plain fields and a read at the secret one publishes, through the real
   `mist.api.write` node - Task 3.
3. A constant carried through a comprehension over constants, `["s3cr3t-value"].map(x, x)[0] + trigger.y`, is
   refused - Tasks 1 and 3.
4. A constant key whose value the target marks (`{"passphrase": trigger.psk}`), or in an object of reads at a
   position marked whole (`{"user": trigger.user, "pw": trigger.pw}`), isn't refused for its key; a constant key where
   the schema marks keys is - Tasks 2 and 3.
5. A macro at a sensitive boolean position (`trigger.list.all(x, x > 0)`) isn't refused for its own `true` - Tasks 1
   and 3.

## Tasks

### Task 1: the analysis, `engine/cel/written.py` (new)

**Files:** create `backend/src/dewpoint/engine/cel/written.py`; test `backend/tests/engine/cel/test_written.py`.

**Produces:** `reaching(root: Expr) -> frozenset[Position]`; `Position = tuple[str | int | Wild, ...]`;
`Wild.ANY` (anywhere at or under the positions before it), `Wild.KEY` (a key of the map at the positions before it).

- [ ] Write the tests: a table of `(expression, expected positions)`, each expression parsed with
  `cel_runtime.parse` and its positions compared with `reaching(parsed.expr)`:

```python
@pytest.mark.parametrize(("expr", "expected"), [
    ('"s3cr3t-value"', {()}), ("null", {()}), ("true", {()}), ("-5", {()}), ('b"x"', {()}),
    ("trigger.tok", set()), (".trigger.tok", set()),
    ('"Bearer " + trigger.tok', {()}), ('"" + trigger.tok', set()), ('b"" + trigger.b', set()),
    ('trigger.n > 0 ? "s3cr3t-value" : ""', {()}), ('"s3cr3t-value" == trigger.tok ? trigger.a : trigger.b', set()),
    ("trigger.n + 1", {()}), ("-trigger.n", set()), ('string(4242)', {()}), ('timestamp("2020-01-01T00:00:00Z").getHours("+05:00")', {()}),
    ('trigger.t.getHours("+05:00")', set()),
    ('size("s3cr3t-value")', set()), ('"a" in trigger.l', set()), ('has(trigger.x)', set()),
    ('trigger.tok.startsWith("ab")', set()), ('type("x") == type(trigger.x)', set()),
    ('ipInCidr(trigger.ip, "10.0.0.0/8")', set()), ('macNormalize("aa:bb:cc:dd:ee:ff")', {()}),
    ('trigger.headers["Authorization"]', set()), ("trigger.toks[0]", set()),
    ('{"ssid": "corp", "passphrase": trigger.psk}', {(Wild.KEY,), ("ssid",)}),
    ('{trigger.k: "s3cr3t-value"}', {(Wild.ANY,)}), ('["a", trigger.x]', {(0,)}),
    ('["a"] + trigger.l', {(Wild.ANY,)}), ('{"a": "s3cr3t-value"}.a', {()}), ('{"a": "s3cr3t-value"}[trigger.k]', {()}),
    ('{"a": ["s3cr3t-value"]}.b', set()), ('sortedKeys({"s3cr3t-value": 1})', {(Wild.ANY,)}),
    ('dyn("s3cr3t-value")', {()}), ('asList(["s3cr3t-value"])', {(0,)}),
    ('["s3cr3t-value"].map(x, x)[0] + trigger.y', {(Wild.ANY,)}), ('{"s3cr3t-value": 1}.map(k, k)', {(Wild.ANY,)}),
    ("trigger.l.map(x, x + 1)", {(Wild.ANY,)}), ("trigger.l.filter(x, x > 0)", set()),
    ("trigger.l.all(x, x > 0)", set()), ("trigger.l.exists(x, x > 0)", set()), ("trigger.l.exists_one(x, x > 0)", set()),
    ('["s3cr3t-value"].map(trigger, trigger)', {(Wild.ANY,)}),  # its own variable, even named as a root
    ('unknownFn(trigger.x, "s3cr3t-value")', {(Wild.ANY,)}),
    ("trigger.flag ? [] : trigger.lst", {()}), ("trigger.flag ? {} : trigger.obj", {(), (Wild.KEY,)}),  # written empties
    ("[trigger.a, trigger.b]", set()), ("{trigger.k: trigger.v}", set()), ("trigger.l.map(x, x)", set()),
    # keys keep their provenance (the owner's second plan review): maps of reads stay structure through widening
    ('[{"pw": trigger.pw}] + [{"pw": trigger.pw}]', {KEYS_BELOW}), ('trigger.lst.map(x, {"pw": trigger.pw})', {KEYS_BELOW}),
    ('[{"pw": trigger.pw}].filter(x, true)', {KEYS_BELOW}), ('{trigger.k: {"pw": trigger.pw}}', {KEYS_BELOW}),
    ('[{"pw": trigger.pw}][trigger.i]', {(Wild.KEY,)}), ('trigger.lst.map(x, {"pw": trigger.pw})[0]', {KEYS_UNDER}),
    ('([{"pw": trigger.pw}] + trigger.l).map(y, y)', {KEYS_BELOW}),
    # ... and turn into values where their own map is iterated, or sortedKeys reads them
    ('["x"].map(i, {"s3cr3t-value": trigger.v})[0].map(k, k)', {(Wild.ANY,)}),
    ('{"s3cr3t-value": trigger.v}.map(k, k)', {(Wild.ANY,)}), ('sortedKeys([{"s3cr3t-value": trigger.v}][0])', {(Wild.ANY,)}),
    ('sortedKeys(trigger.lst.map(x, {"pw": trigger.pw})[0])', {(Wild.ANY,)}),
])
def test_where_a_written_constant_lands(expr: str, expected: set[Position]) -> None:
    assert set(written.reaching(cel_runtime.parse(expr).expr)) == expected
```

  Plus: every function name the facts list is in exactly one of the two tables (`CARRIES`, `STOPS`), so the default
  for an unknown one applies only outside this runtime; and a hand-built comprehension with `iter_var2` (the protos
  carry it, no macro here writes it) binds both variables anywhere.
- [ ] Run them: they fail (`ModuleNotFoundError`).
- [ ] Write the module:

```python
# SPDX-License-Identifier: Apache-2.0
"""Where the constants written into a CEL expression may land in its value (engine 2b spec §3.8, issue #79).

Publish refuses a value written at a sensitive position. A formula that reads run data can still carry a constant it
writes into its result (`"Bearer " + trigger.tok`, `trigger.n > 0 ? "…" : ""`). This walk follows each constant on
the parsed AST through what carries it, and stops at what doesn't (see `CARRIES` and `STOPS`); a function neither
names carries every constant of its operands anywhere. Every constant counts — text, bytes, numbers, booleans,
null — but empty text or bytes joined by `+`, which writes nothing (as empty text beside a template's reference). An
empty list or map the author writes is written whole, as the literal is (an empty map's keys with it, so it counts
where keys are marked, as the literal `{}` does); one holding reads writes only the constants it holds. A macro's
accumulator start (`@result`, from `true`, `false`, `0` or an empty list) is the macro's, not the author's: it's never
walked.

A position names where a constant may land: map keys and list indexes as written, then at most one of
- `(KEY,)`: a key of the map there;
- `(ANY, KEY)`: a key of a map at or under there; `(BELOW, KEY)`: a key of a map strictly under there. A key keeps
  being a key when the walk loses its path (a list concatenated, a map's value under a key chosen at run time), so a
  map of reads stays structure (the owner's second plan review); only iterating a value whose own keys it may be
  turns it into a value (`_elements`), and `sortedKeys` does;
- `(ANY,)`: anything, keys included, anywhere at or under there."""

import enum

from dewpoint.engine.cel.ast import Expr, operands


class Wild(enum.Enum):
    ANY = "any"
    BELOW = "below"
    KEY = "key"


Position = tuple[str | int | Wild, ...]
Reach = frozenset[Position]
NONE: Reach = frozenset()
WHOLE: Reach = frozenset({()})
ANYWHERE: Reach = frozenset({(Wild.ANY,)})
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
    return _reach(root, {})


KEYS_BELOW: Position = (Wild.BELOW, Wild.KEY)
KEYS_UNDER: Position = (Wild.ANY, Wild.KEY)


def _deeper(p: Position) -> Position:
    """`p`, read from a value one level or more above the one it was relative to, its path lost: a key stays a key,
    strictly below; anything else is anywhere."""
    return KEYS_BELOW if p and p[-1] is Wild.KEY else (Wild.ANY,)


def _below(reach: Reach, key: str | int | None) -> Reach:
    """What a field read or an index by `key` (None: chosen at run time) gives of a value holding `reach`."""
    out: set[Position] = set()
    for p in reach:
        if not p or p[0] is Wild.KEY:
            continue  # a scalar has no part, and the value's own keys aren't a value
        if p[0] is Wild.ANY:
            out.add(p)  # anything, or keys, still at or under
        elif p[0] is Wild.BELOW:
            out.add(KEYS_UNDER)  # keys strictly under: the part read may be their map
        elif key is None or p[0] == key:
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
            out.add((Wild.ANY,))  # may be the iterated map's own keys: values now
        elif p[0] is Wild.BELOW:
            out.add(KEYS_UNDER)  # keys inside an element stay keys
        elif isinstance(p[0], int):
            out.add(p[1:])
        # a map's value (a key first) isn't bound: iterating a map binds its keys
    return frozenset(out)


def _flat(reach: Reach) -> Reach:
    """Concatenation keeps a scalar whole and loses an element's index; a key in an element stays a key."""
    return frozenset(p if not p or p[0] in (Wild.ANY, Wild.BELOW) else _deeper(p) for p in reach)


def _empty(e: Expr) -> bool:
    kind = e.const_expr.WhichOneof("constant_kind") if e.WhichOneof("expr_kind") == "const_expr" else None
    return kind in ("string_value", "bytes_value") and not getattr(e.const_expr, kind)


def _key(e: Expr) -> str | int | None:
    """A lookup's key when written as a constant."""
    if e.WhichOneof("expr_kind") != "const_expr":
        return None
    kind = e.const_expr.WhichOneof("constant_kind")
    return getattr(e.const_expr, kind) if kind in ("string_value", "int64_value", "uint64_value") else None


def _macro_start(ce: Expr.Comprehension) -> bool:
    init = ce.accu_init
    if ce.accu_var != MACRO_ACCUMULATOR:
        return False
    if init.WhichOneof("expr_kind") == "list_expr":
        return not init.list_expr.elements
    kind = init.const_expr.WhichOneof("constant_kind") if init.WhichOneof("expr_kind") == "const_expr" else None
    return kind == "bool_value" or (kind == "int64_value" and init.const_expr.int64_value == 0)


def _reach(e: Expr, scope: dict[str, Reach]) -> Reach:
    kind = e.WhichOneof("expr_kind")
    if kind == "const_expr":
        return WHOLE
    if kind == "ident_expr":
        return scope.get(e.ident_expr.name, NONE)  # a global is run data
    if kind == "select_expr":
        return NONE if e.select_expr.test_only else _below(_reach(e.select_expr.operand, scope), e.select_expr.field)
    if kind == "list_expr":
        if not e.list_expr.elements:
            return WHOLE  # written empty (a macro's empty start is never walked)
        return frozenset((i, *p) for i, x in enumerate(e.list_expr.elements) for p in _reach(x, scope))
    if kind == "struct_expr":
        if not e.struct_expr.entries:
            return frozenset({(), (Wild.KEY,)})  # written empty: its value, and its (no) keys where keys are marked
        out: set[Position] = set()
        for entry in e.struct_expr.entries:
            value = _reach(entry.value, scope)
            key = entry.map_key if entry.WhichOneof("key_kind") == "map_key" else None
            if key is not None and _reach(key, scope):
                out.add((Wild.KEY,))
            fixed = _key(key) if key is not None else None
            out |= {(fixed, *p) if isinstance(fixed, str) else _deeper(p) for p in value}
        return frozenset(out)
    if kind == "call_expr":
        return _call(e, scope)
    if kind == "comprehension_expr":
        return _comprehension(e.comprehension_expr, scope)
    return NONE


def _call(e: Expr, scope: dict[str, Reach]) -> Reach:
    function, args = e.call_expr.function, operands(e)
    if function in STOPS:
        return NONE
    if function == "_?_:_" and len(args) == 3:
        return _reach(args[1], scope) | _reach(args[2], scope)
    if function == "_[_]" and len(args) == 2:
        return _below(_reach(args[0], scope), _key(args[1]))
    if function in _ARITHMETIC:
        return _flat(frozenset().union(*(_reach(x, scope) for x in args if not _empty(x))))
    if function in _SCALAR and args:
        return WHOLE if _reach(args[0], scope) else NONE
    if function in ("dyn", "asList") and len(args) == 1:
        return _reach(args[0], scope)
    if function == "sortedKeys" and len(args) == 1:
        keys = any(p and p[0] in (Wild.KEY, Wild.ANY) for p in _reach(args[0], scope))
        return ANYWHERE if keys else NONE
    return ANYWHERE if any(_reach(x, scope) for x in args) else NONE  # unknown: anywhere


def _comprehension(ce: Expr.Comprehension, scope: dict[str, Reach]) -> Reach:
    source = _reach(ce.iter_range, scope)
    bound = {ce.iter_var: _elements(source)}
    if ce.iter_var2:  # no macro of this runtime writes one: both variables, anywhere
        bound = {ce.iter_var: ANYWHERE if source else NONE, ce.iter_var2: ANYWHERE if source else NONE}
    accu = NONE if _macro_start(ce) else _reach(ce.accu_init, scope)
    for _ in range(_ROUNDS):
        grown = accu | _reach(ce.loop_step, {**scope, **bound, ce.accu_var: accu})
        if grown == accu:
            break
        accu = grown
    else:
        accu = ANYWHERE if accu else NONE
    return _reach(ce.result, {**scope, ce.accu_var: accu})
```

- [ ] Run the tests: they pass. Mutation-check: drop the `+` empty-text exemption, make `_?_:_` carry its
  condition, drop `_macro_start`, make the unknown default carry nothing, drop `KEY` from map construction, make
  `_below` ignore the key, drop either written-empty rule, make `_deeper` turn a key into anywhere (the second review's
  regression), make `_elements` keep `KEYS_UNDER` a key, make `_below` keep `BELOW`: each fails a test.

### Task 2: where a position lands, `engine/sensitive.py`

**Files:** modify `backend/src/dewpoint/engine/sensitive.py`; test `backend/tests/engine/test_sensitive.py` (new).

**Produces** (each navigating from the schema's root as `is_marked` does: `expand`, `children`, `elements`, so a
tuple position, a union's branches, a pattern, `additionalProperties` and a local `$ref` are followed):
- `may_hold_marked(schema, path, root=None) -> bool`: a value at `path` lies at or under a marked part, or may hold
  one (under a property, a pattern, `additionalProperties`, `items` or a tuple position, a union's branch, a local
  `$ref`, or a map whose keys are);
- `keys_marked(schema, path, root=None) -> bool`: the schema marks the keys of a map at `path` (`propertyNames`);
- `may_mark_keys(schema, path, root=None, below=False) -> bool`: the schema marks the keys of some map at or under
  `path` (strictly under with `below`), following what `may_hold_marked` follows, never counting a key because its
  map lies at a marked position;
- `marked_positions_at(value, schema, path, root=None) -> list[str]`: `marked_positions` of a value written at
  `path`, relative to it.
And (ruling 7) `marked_positions` counts a map whose keys are marked even when its values are all holes.

- [ ] Write the tests, each against a small schema:
  - `may_hold_marked`: a marked property under the path, a pattern, `additionalProperties`, `items`, `prefixItems`,
    an `anyOf` branch, a `$ref` (to a marked definition, and to one no position reaches), and `propertyNames`, each
    `True`; a plain schema and a `not` holding a mark, `False`; a path under a marked part, `True`; a path through a
    tuple position (`("x", 0)` under `prefixItems`) and through a union's branch (`("x", "y")` under `anyOf`), `True`;
  - `keys_marked`: `True` for `propertyNames` marked; `False` where only a key's value is marked (`{"properties":
    {"passphrase": SECRET}}` at `()`), and at a map marked whole (`{"x-sensitive": true, "properties": …}`);
  - `may_mark_keys`: `True` for an array whose `items` mark keys, at and below; for a map marking its own keys, `True`
    at and `False` below; `False` for an array marked whole and for one whose items mark only `pw`'s value;
  - `marked_positions_at`: `{"pw": "lit-value"}` at a tuple position and inside a union's branch gives `["/pw"]`;
    `{"user": "ops"}` there gives `[]`;
  - ruling 7: `marked_positions({"k3y-value": HOLE}, keys-marked schema, holes={"/k3y-value"})` gives `[""]`; an
    object of holes at a position marked whole still gives `[]`.
- [ ] Run them: they fail (`ImportError`; ruling 7's first case gives `[]`).
- [ ] Write the helpers, walking what's below as `validate._holds_marked` does (which they replace):

```python
def _schemas_at(schema: Mapping[str, Any], path: tuple[str | int, ...], root: Mapping[str, Any]) -> list[Any]:
    """The schemas that may govern the value at `path`, navigated as `is_marked` navigates."""
    schemas: list[Any] = [schema]
    for part in path:
        branches = [b for s in schemas for b in expand(s, root)]
        schemas = elements(branches, part) if isinstance(part, int) else children(branches, part)
    return schemas


def may_hold_marked(schema: Mapping[str, Any], path: tuple[str | int, ...], root: Mapping[str, Any] | None = None) -> bool:
    """Whether a value written at `path` may put something at a part the schema marks: the position lies at or under a
    marked part, or a part of it may be marked (a property, a pattern, `additionalProperties`, `items`, a tuple
    position, a union's branch, a local `$ref`, sensitive keys)."""
    resolve_in = root if root is not None else schema
    if is_marked(schema, path, resolve_in):
        return True
    seen: set[int] = set()
    stack: list[Any] = list(_schemas_at(schema, path, resolve_in))
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        branches = expand(node, resolve_in)
        if any(b.get(SENSITIVE) is True for b in branches) or keys_sensitive(branches, resolve_in):
            return True
        stack += map_values(branches)
        for b in branches:
            props, prefix = b.get("properties"), b.get("prefixItems")
            stack += list(props.values()) if isinstance(props, Mapping) else []
            stack += prefix if isinstance(prefix, list) else []
            stack += [b["items"]] if isinstance(b.get("items"), Mapping) else []
    return False


def keys_marked(schema: Mapping[str, Any], path: tuple[str | int, ...], root: Mapping[str, Any] | None = None) -> bool:
    """Whether the schema marks the keys of a map written at `path` (`propertyNames`). A map at a marked position, or
    one whose key's value is marked, doesn't make its keys sensitive: an object of references there writes no
    literal, its keys included (they're structure)."""
    resolve_in = root if root is not None else schema
    branches = [b for s in _schemas_at(schema, path, resolve_in) for b in expand(s, resolve_in)]
    return keys_sensitive(branches, resolve_in)


def may_mark_keys(
    schema: Mapping[str, Any], path: tuple[str | int, ...], root: Mapping[str, Any] | None = None, below: bool = False
) -> bool:
    """Whether the schema marks the keys of some map at or under `path` (strictly under, with `below`): where a key
    whose path publish lost may land. As `keys_marked`, a marked position doesn't make its keys sensitive."""
    resolve_in = root if root is not None else schema
    seen: set[tuple[int, bool]] = set()
    stack: list[tuple[Any, bool]] = [(s, below) for s in _schemas_at(schema, path, resolve_in)]
    while stack:
        node, skip = stack.pop()
        if (id(node), skip) in seen:
            continue
        seen.add((id(node), skip))
        branches = expand(node, resolve_in)
        if not skip and keys_sensitive(branches, resolve_in):
            return True
        nested: list[Any] = map_values(branches)
        for b in branches:
            props, prefix = b.get("properties"), b.get("prefixItems")
            nested += list(props.values()) if isinstance(props, Mapping) else []
            nested += prefix if isinstance(prefix, list) else []
            nested += [b["items"]] if isinstance(b.get("items"), Mapping) else []
        stack += [(c, False) for c in nested]
    return False


def marked_positions_at(
    value: Any, schema: Mapping[str, Any], path: tuple[str | int, ...], root: Mapping[str, Any] | None = None
) -> list[str]:
    """`marked_positions` of a value written at `path` of the schema's instances, relative to it, navigated as
    `is_marked` navigates: never through one resolved subschema, which a tuple position or a union's branches defeat.
    Whether the position itself is marked is `is_marked`'s question."""
    resolve_in = root if root is not None else schema
    out: list[str] = []
    _marked(value, _schemas_at(schema, path, resolve_in), resolve_in, "", out, ())
    return out
```

  And ruling 7 in `_marked`: a map whose keys are marked writes them whatever its values are; a part marked whole
  and made only of holes still writes nothing:

```python
    marked = any(b.get(SENSITIVE) is True for b in branches)
    if (marked and not _holes_only(value, pointer, holes)) or (isinstance(value, dict) and keys_sensitive(branches, root)):
        out.append(pointer)
    elif isinstance(value, dict):
```

  (`marked_positions` without holes, as the worker calls it for a step's config, `apps/worker/claims.py`, gives what
  it gave: with no holes `_holes_only` is false for every value, so both conditions append as before. Only the
  validator's node-config check passes holes, `validate.py` `_sensitive_literals`.)
- [ ] Run the tests: they pass. Mutation-check: drop the walk's `map_values`, `prefixItems` or `keys_sensitive`;
  make `keys_marked` use `may_hold_marked`; make `marked_positions_at` start from `[schema]`; restore `_holes_only`
  on the keys condition; make `may_mark_keys` ignore `below`, or count a marked position: each fails a test.

### Task 3: the validator refuses a carried constant at a marked part

**Files:** modify `backend/src/dewpoint/engine/graph/validate.py` (`_reads_nothing`, `_writes_sensitive`); tests
`backend/tests/engine/graph/test_validate_sensitive.py`, `backend/tests/plugins/mist/test_api_nodes.py`.

**Consumes:** `written.reaching`, `written.Wild`, `written.Position` (Task 1); `may_hold_marked`, `keys_marked`,
`may_mark_keys`, `marked_positions_at`, `is_marked` (Task 2).

- [ ] Write the tests:
  - at testkit `ambiguous_send` `/token` (`x-sensitive`): the issue's four examples, `has(trigger.tok) ?
    trigger.tok : ""` and `... : null`, `["s3cr3t-value"].map(x, x)[0] + trigger.y` and `string(4242) + trigger.tok`
    each give `[("sensitive.literal", "/token")]`; review focus 1's formulas give `[]`;
  - a sensitive variable (`set_variables`, `vars_schema` with a sensitive `login` part as `LOGIN_VARS`):
    `{"user": "ops", "pw": trigger.pw}` passes, `{"user": trigger.user, "pw": "pa55-" + trigger.pw}` is refused, a
    list under `items: SECRET` with a constant element beside a read refused, a map under `propertyNames` sensitive
    with a constant key refused, `{"pw": trigger.pw}` under `{"properties": {"pw": SECRET}}` passes, and
    `{"user": trigger.user, "pw": trigger.pw}` at a login marked whole passes (review focus 4);
  - written empties (the review's Low): at a list and at an object marked whole, `trigger.flag ? [] : trigger.lst` and
    `trigger.flag ? {} : trigger.obj` are refused, as the literals `[]` and `{}` are; `trigger.l.map(x, x)` passes;
  - keys through widening (the second review's Medium), at an array marked whole and at one whose items mark only
    `pw`: `[{"pw": trigger.pw}] + [{"pw": trigger.pw}]`, `trigger.lst.map(x, {"pw": trigger.pw})` and
    `[{"pw": trigger.pw}].filter(x, true)` pass, as the written list of references does; at an array whose items mark
    their keys, `trigger.lst.map(x, {"k3y-value": trigger.v})` is refused; at an array marked whole, a written key
    turned into a value is refused: `["x"].map(i, {"s3cr3t-value": trigger.v})[0].map(k, k)` and
    `sortedKeys({"s3cr3t-value": trigger.v})`;
  - nested envelopes (the review's Medium and its siblings, ruling 6), for a variable `x` whose schema is a tuple of
    `{"pw": SECRET}` objects (envelope at `/x/0`) and a union whose branch holds `y: {"pw": SECRET}` (envelope at
    `/x/y`): a formula reading the run `{"pw": "lit-" + trigger.s}`, a formula reading nothing `{"pw":
    "lit-value"}`, a reference's default `{"pw": "lit-value"}` and a literal envelope `{"pw": "lit-value"}` are each
    refused at the envelope's field; `{"pw": trigger.pw}` as a formula and a reference without a default pass;
  - ruling 7: `{"k3y-value": ref("trigger.v")}` where the map's keys are marked is refused; the existing
    `test_a_sensitive_object_built_from_references_writes_no_literal` still passes;
  - a sensitive boolean variable: `trigger.l.all(x, x > 0)` passes, `trigger.n > 0 ? true : false` refused (review
    focus 5);
  - a sub-flow's sensitive input field: `"Bearer " + trigger.tok` refused at `/input/...`;
  - `mist.api.write` (review focus 2): body `cel('{"ssid": "corp", "passphrase": trigger.psk}')` gives no
    `sensitive.literal`; `cel('{"ssid": trigger.s, "passphrase": "psk-" + trigger.psk}')` gives one at `/body`;
  - the message is `_SENSITIVE_LITERAL` and quotes nothing written in the formula;
  - every existing test in both files unchanged.
- [ ] Run them: the refusals fail (they publish clean today); the passes pass.
- [ ] Wire it, parsing once:

```python
def _cel_writes(expr: str, root: Mapping[str, Any], pointer: Pointer) -> bool:
    """Whether a CEL expression writes a fixed value at a part the target marks (§3.8): it reads no run data (its
    whole value is fixed, refused wherever the caller found a part could be marked), or a constant it writes may land
    at a marked part (`written.reaching`). One that doesn't parse is reported where it's checked."""
    try:
        parsed = cel_runtime.parse(expr)
    except cel_runtime.CompileError:
        return False
    names = cel_ast.global_idents(parsed.expr)
    if not any(n.lstrip(".").split(".")[0] in _RUN_ROOTS for n in names):  # `.trigger`: the root, named from the top
        return True
    return any(_lands_marked(root, pointer, p) for p in written.reaching(parsed.expr))


def _lands_marked(root: Mapping[str, Any], pointer: Pointer, position: written.Position) -> bool:
    """Whether a constant at `position` of the value written at `pointer` may land at a part the schema marks: a value
    at or under a marked part, a key where its map's keys are marked (`written.Position` names the forms)."""
    for i, part in enumerate(position):
        at = (*pointer, *position[:i])
        if part is written.Wild.KEY:
            return keys_marked(root, at)
        if part is written.Wild.BELOW:
            return may_mark_keys(root, at, below=True)
        if part is written.Wild.ANY:
            return may_mark_keys(root, at) if position[-1] is written.Wild.KEY else may_hold_marked(root, at)
    return is_marked(root, (*pointer, *position))
```

  and `_writes_sensitive` reads every envelope through the root (ruling 6), its `target` parameter gone (the call in
  `_value` drops it; `_value` keeps `target` for its type checks):

```python
def _writes_sensitive(value: Value, root: Mapping[str, Any], pointer: Pointer) -> bool:
    """Whether a value envelope writes a literal at a sensitive position (§3.8), read from the config's root as a
    literal written in place is (a tuple position, a union's branches, a pattern, a local `$ref`): the literal itself or
    a reference's default, at it or holding a part the schema marks; a template's default or text (all of it, without a
    reference); a CEL expression that writes a fixed value where it may land at a marked part (`_cel_writes`). Null
    and the empty string are written too; empty text beside a reference writes nothing."""
    marked = is_marked(root, pointer)
    if isinstance(value, LiteralValue):
        return marked or bool(marked_positions_at(value.value, root, pointer))
    if isinstance(value, RefValue):
        return value.has_default and (marked or bool(marked_positions_at(value.default, root, pointer)))
    if isinstance(value, CelValue):
        return may_hold_marked(root, pointer) and _cel_writes(value.expr, root, pointer)
    refs = [p for p in value.parts if isinstance(p, TemplateRef)]
    text = "".join(p for p in value.parts if isinstance(p, str))
    return marked and (not refs or bool(text) or any(p.default is not None for p in refs))
```

  `_reads_nothing` folds into `_cel_writes` (its docstring kept there) and `_holds_marked` is deleted (its walk is
  `may_hold_marked`'s).
- [ ] Run the tests, then the affected suites (`tests/engine`, `tests/plugins`, `tests/apps/api`), which hold
  formulas at sensitive positions: any refused fixture is reported, never silently changed. Mutation-check: the
  `KEY` branch as `may_hold_marked`, `is_marked` for the `ANY` branch, the `BELOW` branch as `may_hold_marked`, the
  `ANY, KEY` form as `may_hold_marked`, the wiring removed, the gate back on
  `target_schema()` (`_holds_marked(target)`), `marked_positions(…, target)` back for a reference's default and for a
  literal envelope: each fails a test.

### Task 4: the spec and this record

- [ ] Engine 2b spec §3.8: the "Not covered" bullet becomes the rule (what carries, rulings 1 to 4, the threat model
  of "Not in scope"); the gate's sentence keeps #76's rule for a formula that reads nothing; a sentence for rulings 6
  and 7 (envelopes read as written in place; a written key where keys are marked).
- [ ] This plan's record: the runs, the review, the checkpoint.

## Reviews

- The owner's technical review of this plan (pasted, 2026-10-14, against b61ede43; 65 checks passed, five regression
  failures): one Medium, the eligibility gate's dependence on `target_schema()` (a nested formula under a tuple
  position or a union's branches went unchecked), and one Low, author-written empty containers missed by the walk.
  Both reproduced here, and the same gate found to fail open for a reference's default and a literal envelope
  (facts). Folded in: rulings 1 and 4 amended, rulings 6 and 7 added, Tasks 1 to 4 extended. Found while folding:
  the plan's first `keys_marked` would have refused an object of reads at a position marked whole, which the literal
  rule allows (ruling 4 now says so; review focus 4 pins it). No build authorization, no ruling sign-off.
- A prototype of this plan's code (scratch only, never the repo; the build starts again from the tests): the AST table
  passes, `test_validate_sensitive.py` and `tests/plugins/mist/test_api_nodes.py` pass unchanged with it patched in,
  and 37 of Task 3's cases (the issue's examples, review focus 1, both nested shapes for all four envelope kinds,
  written empties, keys, the boolean macros, the Mist body) come out as stated.
- The owner's second technical review (pasted, 2026-10-14; 257 checks passed, six regressions): the earlier Medium,
  Low and sibling gaps addressed; one Medium: `_flat()` widened `(0, KEY)` to `ANY`, so a list of maps of reads
  concatenated, mapped or filtered (`[{"pw": trigger.pw}] + [{"pw": trigger.pw}]`, `trigger.lst.map(x, {"pw":
  trigger.pw})`, `[{"pw": trigger.pw}].filter(x, true)`) was refused at an array marked whole and at one whose items
  mark only `pw`, though the written list of references passes. Folded in: positions keep a key's provenance
  (`KEY`, `ANY, KEY`, `BELOW, KEY`), checked against reachable `propertyNames` (`may_mark_keys`); iterating a value
  whose own keys a position may name, and `sortedKeys`, still turn keys into values. Its scope advice: keep ruling 7
  in this slice (advice, not a ruling). No build authorization, no ruling sign-off.

Then a fresh-context review hunting fail-open paths (a constant that lands at a marked part unrefused), fixes
test-first, the affected suites, gitleaks, local CodeQL, a checkpoint; the full suite, commits, push and PR each on
the owner's go.
- The prototype again, on the revised plan at 52314866 (scratch only): the AST table and the unchanged sensitive and
  Mist suites pass (166), the 37 earlier cases and 12 key-provenance cases (the second review's six regressions, a
  written list of references at both arrays, a constant key where items mark keys, a key iterated into a value,
  `sortedKeys` of a written key, a double `map` of reads) come out as stated.

## Build (2026-10-14, on the owner's "go, build it, keep ruling 7 in this slice"; committed on the owner's go)

Tasks 1 to 4 built test-first at 52314866, each test watched failing (an import error for the new modules; every
refusal of Task 3, which published clean before the wiring; ruling 7's key beside a reference), each protection
mutation-checked (37 mutants, all killed; Task 3's ten again after `_lands_marked` was refactored for mypy):
- Task 1 (`engine/cel/written.py`, `tests/engine/cel/test_written.py`, 69 tests): the plan's table, two rows a
  mutant showed missing (a constant index against one chosen at run time; `has()` on a map of constants), every
  declared call classified once, a second comprehension variable; 17 mutants killed.
- Task 2 (`engine/sensitive.py`, `tests/engine/test_sensitive.py`, 30 tests): `may_hold_marked`, `keys_marked`,
  `may_mark_keys`, `marked_positions_at` (sharing `_schemas_at` and `_nested`), ruling 7 in `_marked`; the projection,
  validator and Mist tests unchanged; 10 mutants killed.
- Task 3 (`engine/graph/validate.py`; `test_validate_sensitive.py`, `test_api_nodes.py`): `_cel_writes`,
  `_lands_marked`, `_writes_sensitive` from the root (`_holds_marked` and `_reads_nothing` gone); the cases of the
  plan, a constant concatenated onto a list whose items are marked, and keys read back from a list of maps; four
  Mist bodies through `mist.api.write`; 10 mutants killed.
- Task 4: the spec's §3.8 (the "Not covered" bullet is the rule; envelopes read from the root; ruling 7), and
  `docs/operations/deployment.md`'s list of what's refused as a literal (a template's text and formulas, which it
  didn't name).

A fresh-context review of the build (2026-10-14): one High, two Medium, five Low; fixed test-first:
- High (fail-open): a message built in the expression, `google.protobuf.Struct{fields: {"<key>": trigger.tok}}`,
  was walked as a map whose values sit under a key chosen at run time, so its keys were "strictly under": the Struct's
  `fields` are its object's own keys. `sortedKeys(google.protobuf.Struct{fields: {…}})[0]` at `/token`, at a Mist
  `passphrase`, and the Struct itself where keys are marked, published clean (they type-check). Now a message carries
  every constant of its fields anywhere (ruling 3, amended below).
- Medium (CPU): a comprehension walks its step again until its accumulator settles, so nested macros cost 2^depth
  walks (eight chains of sixteen nested maps: 5 s per validate; extrapolated to about 40 s per 16 KiB expression). The
  walk (`Walk`) now remembers what each node gave for the bindings of the names free in it: linear in the expression,
  pinned by a work-unit test (nodes walked, never time).
- Medium (false positives against the literal rule, a regression for Mist bodies): widening a lost index to
  "anywhere" refused any list a macro or a concatenation built with a constant anywhere in a body whose schema marks
  secret-named fields at every depth (`"wlans": trigger.lst.map(x, {"name": "corp-" + x.name, "psk": x.psk})`,
  `"vlan_ids": [1, 2] + [trigger.n]`), though the written lists publish. Positions now keep the path past a lost step:
  `ITEM` (any element of a list: `items` and every tuple position) or `VALUE` (any value of a map: every property, a
  pattern, `additionalProperties`), never both (a generic schema with secret-named properties and `items` marks no
  element for its properties). This replaced `BELOW` and its key forms; `may_mark_keys` is gone (ruling 4, amended).
- Low, fixed: an empty list joined by `+` writes nothing, as empty text does (ruling 1, amended); test gaps the review's
  mutations showed (a constant in a computed key, a uint index, the accumulator's fallback, now a hand-built AST).
- Low, not changed (the rulings' tables, for the owner): `trigger.b || true`, `trigger.b && false` and
  `[].all(x, trigger.b)` at a sensitive boolean, `trigger.strs.filter(x, false)` at a list marked whole, always write
  the same constant and publish (logical operators carry nothing; a macro's start isn't the author's).
- Low, noted: some "publishes" cases sit on graphs another rule refuses (`sensitive.default` on the test's nullable
  variables, `cel.bad_path` on an unguarded index); the tests read `sensitive.literal` only.
- Outside this change (pre-existing on main): from 17 nested macros `cel_runtime.parse` lets protobuf's `DecodeError`
  through (not a `CompileError`), so `validate()` fails unexpectedly at any field: fixed on its own, PR #102.

Rulings amended by the review's fixes (for the owner's sign-off with the rest):
- Ruling 1: "empty text or bytes joined by `+`" becomes "empty text, bytes or a list joined by `+`".
- Ruling 3: a message built in the expression carries every constant of its fields anywhere, as an unknown function.
- Ruling 4: where publish loses an element's index (a concatenation, a macro) or a value's key (one chosen at run
  time), the constant is checked at every element or value the schema there could give it, the rest of its path kept
  (no longer "anywhere at or under").

The fixes' protections mutation-checked: 30 mutants on the reworked walk, the two schema steps and the validator's
translation, and 13 earlier ones re-run where their text moved, all killed. Ruff, format, `mypy src` clean.

Runs at the reworked code (52314866 plus the uncommitted change): `tests/engine` (the CEL gates apart, `test_written`
and `test_ast` in), `tests/plugins` and `tests/sdk` 2,426 passed; the CEL validation gate (`test_validate_cel.py`) 79;
the app tests holding formulas at sensitive fields (`tests/apps/api`, `test_runs`, `test_workflow_ops`, eight worker
files) 715. An earlier run's three SMTP setup errors were Docker API timeouts while another session's test databases
ran; the file passed alone. gitleaks finds nothing in the changed files (the spec's one `generic-api-key` match is
main's, its line 1700). The 11 import contracts hold. Local CodeQL: 0 (CLI 2.27.2, python-queries 1.8.12). Not run:
the full suite.

Committed on the owner's "commit the cel-literal build" (2026-10-14) as e7022504, after ruff, format, `mypy src` and
the touched files (`test_written`, `test_sensitive`, `test_validate_sensitive`, `test_validate_taint`,
`test_validate_declassify`, `test_api_nodes`: 311 passed) ran clean on the tree again. The commit is the owner's go to
commit only: the amended rulings 1, 3 and 4, and the Low left unchanged for the owner (fixed booleans,
`filter(x, false)`), still await the owner's sign-off. Not pushed.
