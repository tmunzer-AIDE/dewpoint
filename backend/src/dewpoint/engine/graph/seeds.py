# SPDX-License-Identifier: Apache-2.0
"""A single step's seed contract (S2; the simulation design §5.2): what one step of a draft reads, as root-anchored
JSON pointers a person gives values for when the step runs alone.

It asks the validator's converged analysis (`analyze`), its resolver and its guard facts (`cel.guards`), as the data
tree does (`scope.py`), never a copy of their rules. The reads are the step's own context: its refs, its template
parts, and each CEL value's chains, minus what a run binds itself (`run.*`) and what a filter binds per element (its
predicate's `item` and `index`). Each entry's obligations are its uses', the strictest winning: it's required unless
every use tolerates its absence (a default, a `has()` test, or a read a guard proves present); null only where its
schema allows it or every use has a default; sensitive where its taint says. A value given is checked against the
resolver's schema for it, and each read inside it against its own, as the schema stands: inside it, presence and null
come from the uses too (a path a use reads strictly must be there; null where the schema allows it or every use
reading through it has a default), so a schema's `required` (where it obliges, never where it tests) and a null the
uses take are no refusal, in a choice's branches too.

Normalized: a read through a list index is the whole list; the innermost loop's `loops.<key>.item` and `.index` are
`/item` and `/index` (their aliases, and paths below them, are refused, `seed_alias`); a read inside another is the
outer one, which carries the inner reads as paths its value must hold."""

import dataclasses
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple

from jsonschema import Draft202012Validator

from dewpoint.engine.cel import ast, guards, runtime
from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.graph.schema_messages import explain
from dewpoint.engine.graph.schemas import Resolved, json_types
from dewpoint.engine.graph.validate import Analysis, ValidationContext, analyze, site_of
from dewpoint.engine.graph.values import (
    CelValue,
    RefPath,
    RefSyntaxError,
    RefValue,
    TemplateRef,
    TemplateValue,
    iter_values,
    parse_ref,
    pointer_str,
)
from dewpoint.engine.registry import control as C

# The control steps a single-step simulation runs (D-s1); every action (plugin) step runs too.
CONTROL_TARGETS = frozenset({C.IF, C.SWITCH, C.FILTER, C.TRANSFORM, C.SET_VARIABLES})
SEED_MISSING, SEED_ALIAS, SEED_UNKNOWN, SEED_INVALID = "seed_missing", "seed_alias", "seed_unknown", "seed_invalid"
NO_ANALYSIS = "The saved draft has problems that stop its steps being read. Fix them first."
NO_STEP = "This step isn't in the saved draft."
NOT_ALONE = "This step can't be simulated alone: simulate the workflow to see it run."
READS_EVERY = "This step reads every step's results at once, so it can't be simulated alone."
JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object", "null"})
Kind = Literal["strict", "defaulted", "cel", "presence"]
Segs = tuple[str | int, ...]
EVERY = -1  # in a read's path, each element of a list (a filter's `item`); a pointer shows it as `*`
_ANY = Resolved(None, False)  # a resolution no question here asks of


class Hold(NamedTuple):
    """A path, relative to its entry, that a value given must hold. Its first `given` segments are a condition: where
    they're there and not null, the rest must be (a guard's, or the list a filter reads each element of). `*` is each
    element."""

    pointer: str
    given: int = 0

    @property
    def text(self) -> str:
        if not self.given:
            return self.pointer
        return f"{self.pointer} where /{'/'.join(self.pointer.split('/')[1 : self.given + 1])} is there and isn't null"


@dataclass(frozen=True)
class SeedEntry:
    """One value the step reads. `types`: the JSON types it may have (() when any value); `holds`: what a read inside
    it needs there (`Hold`); `schema`: the resolver's for it, which a value given is checked against; `inner`: each
    read inside it, by relative pointer, with its own schema; `null_ok`: relative pointers where null is taken (its
    schema allows it, or every use reading through it does)."""

    pointer: str
    types: tuple[str, ...]
    required: bool
    nullable: bool
    sensitive: bool
    holds: tuple[Hold, ...] = ()
    schema: Mapping[str, Any] | None = field(default=None, compare=False, repr=False)
    inner: tuple[tuple[str, Mapping[str, Any] | None], ...] = field(default=(), compare=False, repr=False)
    null_ok: tuple[str, ...] = field(default=(), compare=False, repr=False)
    keeps_required: bool = field(default=False, compare=False, repr=False)  # a computed filter list reads it


@dataclass(frozen=True)
class SeedContract:
    entries: tuple[SeedEntry, ...] = ()
    aliases: Mapping[str, str] = field(default_factory=dict)  # an alias pointer -> its canonical one
    refused: str | None = None  # why the step can't run alone


@dataclass(frozen=True)
class SeedProblem:
    code: str
    pointer: str
    message: str


def is_target(ref: str, control: bool) -> bool:
    return not control or ref in CONTROL_TARGETS


def escape(segment: str | int) -> str:
    return str(segment).replace("~", "~0").replace("/", "~1")


def _segments(p: RefPath) -> list[str | int]:
    """A reference's pointer segments, root first: the run binds `run`, the rest is the scope's."""
    if p.root in ("steps", "loops"):
        return [p.root, str(p.name), str(p.section), *p.rest]
    if p.root == "vars":
        return ["vars", *([str(p.name)] if p.name is not None else []), *p.rest]
    return [p.root, *p.rest]


def _cut(segments: list[str | int]) -> list[str | int]:
    """A read through a list index is the whole list: a seed never builds a list with gaps."""
    for i, seg in enumerate(segments):
        if isinstance(seg, int):
            return segments[:i]
    return segments


def _ref_of(segments: Sequence[str | int]) -> RefPath | None:
    text = ""
    for i, seg in enumerate(segments):
        if isinstance(seg, int):
            text += f"[{seg}]"
        elif i == 0:
            text = seg
        else:
            text += f".{seg}"
    try:
        return parse_ref(text)
    except RefSyntaxError:
        return None


Read = tuple[list[str | int], Kind, frozenset[Segs], frozenset[Segs]]  # path, kind, proven present, proven not null


def _cel_reads(record: ExpressionRecord) -> list[Read] | str:
    """A CEL value's reads, as validation checked it: each chain from a root (a typed path read whole), its kind, the
    paths its guards prove present wherever it's read (`has()`), and those they prove not null (`!= null`, or an
    object by `type(x) == type({})`), from the validator's own `guards.facts_at`. A refusal when it can't be read so,
    or reads every step's results at once."""
    try:
        checked = runtime.compile_checked(record.expr, record.declarations).checked
    except runtime.CompileError:
        return NO_ANALYSIS
    facts = guards.facts_at(checked.expr)
    non_null = guards.facts_at(checked.expr, guards.non_null)
    shapes = guards.facts_at(checked.expr, guards.shape)
    reads: list[Read] = []
    short: set[str] = set()
    long: set[str] = set()
    for chain in ast.chains(checked.expr):
        proven = frozenset(facts.get(chain.expr_id, frozenset()))
        set_ = frozenset(non_null.get(chain.expr_id, frozenset()) | shapes.get(chain.expr_id, frozenset()))
        if "." in chain.ident:
            p = _ref_of(chain.ident.split("."))
            if p is not None:
                reads.append((_segments(p), "cel", proven, set_))
            continue
        if chain.ident not in record.declarations:
            continue
        if chain.root in ("steps", "loops"):
            (long if len(chain.path) >= 3 else short).add(chain.root)
        reads.append((list(chain.path), "presence" if chain.presence else "cel", proven, set_))
    return READS_EVERY if short - long else reads


def _within(outer: Segs, path: Segs) -> bool:
    return path[: len(outer)] == outer


@dataclass(frozen=True)
class _Use:
    """One read of the step's, at its canonical segments. `strict`: a ref or template part without a default;
    `defaulted`: one with a default, which replaces a missing or null value; `cel`: a CEL value read; `presence`: a
    `has()` test, which reads only whether the value is there. `proven`: what its guards prove present (CEL);
    `non_null`: what they prove not null, a condition for what it reads below, never for absence (`x != null` fails
    where `x` is missing)."""

    segs: Segs
    r: Resolved
    kind: Kind
    proven: frozenset[Segs] = frozenset()
    read: Segs = ()  # what it reads, before a list index (or each element, EVERY) cut it to `segs`
    at: str = ""  # the field it's read at
    non_null: frozenset[Segs] = frozenset()

    @property
    def needed(self) -> Segs:
        """What must be there for it not to fail, as it reads (a list index or each element included): a `has()` test
        needs only what holds the field it tests."""
        read = self.read or self.segs
        return read[:-1] if self.kind == "presence" else read

    def tolerates_absence(self, entry: Segs) -> bool:
        """Whether `entry` (this read or one outside it) may be absent: a default takes its place, a `has()` test of
        it is false, a read of each element meets none, or a guard proves it, or something inside it on the way,
        present wherever this is read."""
        if self.kind == "defaulted" or (self.kind == "presence" and entry == self.segs):
            return True
        if EVERY in self.needed[len(entry) :]:
            return True
        return any(_within(entry, q) and _within(q, self.needed) for q in self.proven)

    def needs_inside(self, entry: Segs) -> Hold | None:
        """What it needs inside `entry`'s value when that's given: the rest of its path, held where what comes first is
        there. A filter's read of each element needs nothing of an absent or empty list; a guard's read needs nothing
        where what the guard proves present isn't."""
        if self.kind == "defaulted" or len(self.needed) <= len(entry):
            return None
        rest = self.needed[len(entry) :]
        given = rest.index(EVERY) if EVERY in rest else 0
        for q in self.proven | self.non_null:
            if len(q) > len(entry) and _within(entry, q) and _within(q, self.needed):
                given = max(given, len(q) - len(entry))
        return Hold(_pointer(rest), given) if given < len(rest) else None

    def takes_null(self, place: Segs) -> bool:
        """Whether a null at `place` (this read, or a place on its way) is fine for it: a default takes its place, or it
        reads each element of a list at or below there, and a null one has none."""
        return self.kind == "defaulted" or EVERY in self.needed[len(place) :]


def _resolved(v: Any, site: Any, segs: Segs) -> Resolved | None:
    if segs == ("vars",):  # the variables as a whole (`size(vars)`): every declared one, typed by its schema
        return Resolved({"type": "object"}, False, v.vars_shape)
    p = _ref_of(segs)
    return v._resolve(site, p, report=False) if p is not None else None


def _pointer(segs: Sequence[str | int]) -> str:
    return "/" + "/".join("*" if x == EVERY else escape(x) for x in segs)


def _entry(segs: Segs, uses: list[_Use]) -> SeedEntry:
    """An outer read and the reads inside it, as one entry: the strictest use wins (§5.2)."""
    own = [u for u in uses if u.segs == segs]
    r = own[0].r
    types = json_types(r.schema)
    inner: dict[str, Mapping[str, Any] | None] = {}
    null_ok: set[str] = set()
    through: dict[Segs, list[_Use]] = {}  # each place inside the value a use reads through, list indexes too
    for u in uses:
        rel = u.segs[len(segs) :]
        if rel:
            inner.setdefault(_pointer(rel), u.r.schema)
            if u.r.nullable:
                null_ok.add(_pointer(rel))
        read = u.read[len(segs) :]
        for k in range(1, len(read) + 1):
            through.setdefault(read[:k], []).append(u)
    null_ok |= {_pointer(place) for place, by in through.items() if all(u.takes_null((*segs, *place)) for u in by)}
    return SeedEntry(
        pointer=_pointer(segs),
        types=tuple(sorted(types)) if types is not None and types <= JSON_TYPES else (),
        required=not all(u.tolerates_absence(segs) for u in uses),
        nullable=r.nullable or all(u.takes_null(segs) for u in uses),
        sensitive=r.taint.tainted,
        holds=tuple(sorted({h for u in uses if (h := u.needs_inside(segs)) is not None})),
        schema=r.schema,
        inner=tuple(sorted(inner.items())),
        null_ok=tuple(sorted(null_ok)),
    )


def contract(graph: Any, ctx: ValidationContext, node: uuid.UUID) -> SeedContract:
    a = analyze(graph, ctx)
    return contract_of(a, node)


def contract_of(a: Analysis, node: uuid.UUID) -> SeedContract:
    if a.structure is None or a.validator is None:
        return SeedContract(refused=NO_ANALYSIS)
    s, v = a.structure, a.validator
    if node not in s.nodes:
        return SeedContract(refused=NO_STEP)
    spec = s.specs[node]
    if not is_target(spec.ref, spec.kind == "control"):
        return SeedContract(refused=NOT_ALONE)
    records = {r.field: r for r in v.expressions if r.node == str(node)}
    config = {pointer_str(pointer): value for pointer, value in iter_values(s.nodes[node].config)}
    element = _element_of(config.get("/items"), records.get("/items")) if spec.ref == C.FILTER else None
    computed = False  # a filter's predicate reads elements of a list its items compute
    found: list[tuple[list[str | int], str, Kind, frozenset[Segs], frozenset[Segs]]] = []  # each read, where it's read
    for at, value in config.items():
        per_element = spec.ref == C.FILTER and at.startswith("/predicate")
        none: frozenset[Segs] = frozenset()
        reads: list[Read] = []
        if isinstance(value, RefValue):
            reads.append((_segments(value.path), "defaulted" if value.has_default else "strict", none, none))
        elif isinstance(value, TemplateValue):
            reads += [(_segments(part.path), "strict" if part.default is None else "defaulted", none, none)
                      for part in value.parts if isinstance(part, TemplateRef)]  # fmt: skip
        elif isinstance(value, CelValue) and at in records:
            cel = _cel_reads(records[at])
            if isinstance(cel, str):
                return SeedContract(refused=cel)
            reads += cel
        for path, kind, proven, set_ in reads:
            if path[0] == "run" or (per_element and path[0] == "index"):
                continue
            if per_element and path[0] == "item":  # each element of the filtered list, or a list computed
                if element is None:  # what it needs can't be traced to a seed: the items' sources keep `required`
                    strict = _Use(("item",), _ANY, kind, proven, tuple(path), non_null=set_).needs_inside(("item",))
                    computed = computed or strict is not None
                    continue
                path = [*element, EVERY, *path[1:]]
                proven = frozenset((*element, EVERY, *q[1:]) if q[:1] == ("item",) else q for q in proven)
                set_ = frozenset((*element, EVERY, *q[1:]) if q[:1] == ("item",) else q for q in set_)
            found.append((path, at, kind, proven, set_))
    innermost = s.region_of[node]
    key = s.nodes[innermost].key if innermost is not None and s.specs[innermost].ref == C.LOOP else None
    aliases = {f"/loops/{escape(key)}/{name}": f"/{name}" for name in ("item", "index")} if key is not None else {}

    def unaliased(path: Sequence[str | int]) -> Segs:
        if key is not None and tuple(path[:2]) == ("loops", key) and len(path) >= 3:
            return (str(path[2]), *path[3:])  # the innermost frame's alias
        return tuple(path)

    def canonical(path: Sequence[str | int]) -> Segs:
        return tuple(_cut(list(unaliased(path))))

    uses: list[_Use] = []
    for segments, at, kind, proven, set_ in found:
        segs = canonical(segments)
        r = _resolved(v, site_of(s, node, at), segs)
        if r is None:
            return SeedContract(refused=NO_ANALYSIS)
        uses.append(_Use(segs, r, kind, frozenset(unaliased(q) for q in proven), unaliased(segments), at,
                         frozenset(unaliased(q) for q in set_)))  # fmt: skip
    keeps = {u.segs for u in uses if u.at == "/items"} if computed else set()
    outer: list[Segs] = []
    for segs in sorted({u.segs for u in uses}, key=len):
        if not any(_within(o, segs) for o in outer):
            outer.append(segs)
    entries = [_entry(o, [u for u in uses if _within(o, u.segs)]) for o in outer]
    entries = [dataclasses.replace(e, keeps_required=True) if any(_within(o, k) for k in keeps) else e
               for o, e in zip(outer, entries, strict=True)]  # fmt: skip
    return SeedContract(tuple(sorted(entries, key=lambda e: e.pointer)), aliases)


def _element_of(items: Any, record: ExpressionRecord | None) -> list[str | int] | None:
    """What a filter's `item` is an element of, when its items are a path (a ref, or a CEL value that's only a path):
    the predicate's reads then bind each element of that list. None when the items are computed."""
    if isinstance(items, RefValue):
        return _segments(items.path)
    if not isinstance(items, CelValue) or record is None:
        return None
    try:
        checked = runtime.compile_checked(record.expr, record.declarations).checked
    except runtime.CompileError:
        return None
    chains = ast.chains(checked.expr)
    if len(chains) != 1 or chains[0].presence or chains[0].expr_id != checked.expr.id:
        return None
    p = _ref_of(chains[0].ident.split(".") if "." in chains[0].ident else chains[0].path)
    return _segments(p) if p is not None else None


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


_ABSENT = object()


def _get(value: Any, pointer: str) -> Any:
    """What `pointer` (relative, "/a/b") holds in `value`, or _ABSENT."""
    for raw in pointer.split("/")[1:]:
        seg = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping) or seg not in value:
            return _ABSENT
        value = value[seg]
    return value


def _lacks(value: Any, hold: Hold) -> bool:
    """Whether `value` breaks `hold`: a segment missing past its condition. One missing within the condition, or a
    list with no element where it says `*`, needs nothing; a list index is followed as one."""
    return _lacking(value, hold.pointer.split("/")[1:], hold.given)


def _lacking(value: Any, segs: list[str], given: int) -> bool:
    for i, raw in enumerate(segs):
        if raw == "*":
            if not isinstance(value, list):
                return False  # not a list: its type is the schema's to refuse
            return any(_lacking(element, segs[i + 1 :], max(0, given - i - 1)) for element in value)
        found: Any = _ABSENT
        if isinstance(value, Mapping):
            found = value.get(raw.replace("~1", "/").replace("~0", "~"), _ABSENT)
        elif isinstance(value, list) and raw.isdigit():
            found = value[int(raw)] if int(raw) < len(value) else _ABSENT
        if found is _ABSENT or (found is None and i < len(segs) - 1):  # nothing there, or nothing to go into
            return i >= given
        value = found
    return False


def _matches(place: str, patterns: Sequence[str]) -> bool:
    """Whether `place` (a pointer) is one of `patterns`, a `*` in a pattern standing for any list index."""
    parts = place.split("/")
    for pattern in patterns:
        expected = pattern.split("/")
        if len(expected) == len(parts) and all(
            e == p or (e == "*" and p.isdigit()) for e, p in zip(expected, parts, strict=True)
        ):
            return True
    return False


PRESENCE = frozenset({"required", "dependentRequired"})  # where they oblige: §5.2 takes presence from the uses


def _excused(e: Any, null_ok: Sequence[str], at: str, presence: bool = True) -> bool:
    """Whether a schema error is none for a seed: a presence the schema obliges (its uses decide, unless `presence`
    is off), or a null at a place the uses take one. A choice (`anyOf`, `oneOf`) passes when a branch has nothing left
    once these are excused: what was excused stands for a value the run supplies, which picks its own branch. `not`
    and `if` keep their own meaning, since their errors are never these."""
    if (presence and e.validator in PRESENCE) or (
        e.instance is None and _matches(at + pointer_str(tuple(e.absolute_path)), null_ok)
    ):
        return True
    if e.validator in ("anyOf", "oneOf") and e.context:
        branches: dict[Any, list[Any]] = {}
        for sub in e.context:
            branches.setdefault(sub.relative_schema_path[0], []).append(sub)
        return any(all(_excused(sub, null_ok, at, presence) for sub in errors) for errors in branches.values())
    return False


def _schema_problem(
    schema: Mapping[str, Any] | None, value: Any, null_ok: Sequence[str], at: str = "", presence: bool = True
) -> str | None:
    """The first way `value` breaks `schema`, as it stands, that the uses don't excuse; worded with where (the
    validator's own words, `explain`)."""
    if schema is None:
        return None
    errors = Draft202012Validator(schema).iter_errors(value)
    for e in sorted(errors, key=lambda e: str(list(e.absolute_path))):
        if _excused(e, null_ok, at, presence):
            continue
        where = at + pointer_str(tuple(e.absolute_path))
        return f"At {where}: {explain(e)}" if where else explain(e)
    return None


def _invalid(e: SeedEntry, value: Any) -> str | None:
    """Why a non-null `value` doesn't fit `e`: its type, a path a read inside needs, its schema, or a read inside's."""
    kind = _json_type(value)
    if e.types and not (kind in e.types or (kind == "integer" and "number" in e.types)):  # a whole number is a number
        return f"This value must be {' or '.join(e.types)}."
    missing = [h.text for h in e.holds if _lacks(value, h)]
    if missing:
        return f"This value must hold {', '.join(missing)}."
    excuse = not e.keeps_required
    found = _schema_problem(e.schema, value, e.null_ok, presence=excuse)
    for at, schema in e.inner:
        if found is not None:
            break
        inside = _get(value, at)
        if inside is not _ABSENT:
            found = _schema_problem(schema, inside, e.null_ok, at, presence=excuse)
    return found


def _alias_of(aliases: Mapping[str, str], pointer: str) -> str | None:
    """The canonical pointer for an alias, or for a path below one."""
    for alias, canonical in aliases.items():
        if pointer == alias or pointer.startswith(alias + "/"):
            return canonical + pointer[len(alias) :]
    return None


def check(c: SeedContract, values: Mapping[str, Any], absent: Sequence[str]) -> list[SeedProblem]:
    """The seeds against the contract (the simulation design §5.2): every entry in exactly one of `values` and
    `absent`; absence only where optional, null only where nullable; each value fitting its schema, holding what a
    read inside it needs; no pointer the contract doesn't list. Problems in pointer order."""
    found: list[SeedProblem] = []
    by_pointer = {e.pointer: e for e in c.entries}
    for p in sorted({*values, *absent}):
        canonical = _alias_of(c.aliases, p)
        if canonical is not None:
            found.append(SeedProblem(SEED_ALIAS, p, f"Give this value at {canonical}: it's the same one."))
        elif p not in by_pointer:
            found.append(SeedProblem(SEED_UNKNOWN, p, "This step doesn't read this value."))
    for e in c.entries:
        given, gone = e.pointer in values, e.pointer in absent
        if given and gone:
            found.append(SeedProblem(SEED_INVALID, e.pointer, "Give a value or leave it absent, not both."))
        elif gone and e.required:
            found.append(SeedProblem(SEED_MISSING, e.pointer, "This value can't be absent: the step reads it."))
        elif not given and not gone:
            found.append(SeedProblem(SEED_MISSING, e.pointer, "Give this value, or leave it absent if it may be."))
        elif given and values[e.pointer] is None:
            if not e.nullable:
                found.append(SeedProblem(SEED_INVALID, e.pointer, "This value can't be null."))
        elif given:
            why = _invalid(e, values[e.pointer])
            if why is not None:
                found.append(SeedProblem(SEED_INVALID, e.pointer, why))
    return sorted(found, key=lambda pr: (pr.pointer, pr.code))
