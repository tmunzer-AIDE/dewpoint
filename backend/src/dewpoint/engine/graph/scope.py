# SPDX-License-Identifier: Apache-2.0
"""What one field of a step can read (sub-project 4, B6; 4c-2a rulings 4–7): every reference available there, as the
validator sees it: its type, whether it may be missing or null, whether it's sensitive, whether a reference can name
it, and the guards a formula needs to read it safely.

It asks the validator's own analysis (`analyze`) and resolver, never a copy of their rules, so the editor's data tree
and validation can't disagree. It writes nothing, and its questions leave no diagnostics behind."""

import re
import uuid
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.graph.model import Graph
from dewpoint.engine.graph.schemas import PathError, Resolved, alternatives, json_types, navigate
from dewpoint.engine.graph.validate import Analysis, ValidationContext, analyze, site_of
from dewpoint.engine.graph.values import CEL_KEYWORDS, MAX_REF_LENGTH, RefPath, RefSyntaxError, parse_ref
from dewpoint.engine.registry import control as C

Root = Literal["trigger", "steps", "vars", "item", "index", "loops", "run"]
GuardKind = Literal["present", "not_null", "is_map", "is_list", "min_size"]
JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object", "null"})
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")  # what a reference names (the ref grammar's field)
MAX_CHILDREN = 500
FIND_DEPTH, FIND_VISITS, FIND_FOUND = 6, 2000, 50
NO_STEP = "This step isn't in the saved draft yet."
NO_ANALYSIS = "The saved draft has problems that stop its steps being read. Fix them first."
UNREADABLE = "The saved draft isn't a workflow yet: fix its format first."  # parse_graph refused it (the API says)


@dataclass(frozen=True)
class Guard:
    """A test a formula makes before it reads a path (4c-2a ruling 6). For `min_size`, `size` is the index the read
    takes: the list must have more items than that."""

    kind: GuardKind
    path: str
    size: int | None = None

    def cel(self) -> str:
        if self.kind == "present":
            return f"has({self.path})"
        if self.kind == "not_null":
            return f"{self.path} != null"
        if self.kind == "is_map":
            return f"type({self.path}) == type({{}})"  # a type's name can't be bound by a run (cel.type_name)
        if self.kind == "is_list":
            return f"type({self.path}) == type([])"
        return f"size({self.path}) > {self.size}"


@dataclass(frozen=True)
class FormulaUse:
    guards: tuple[Guard, ...]
    sensitive: bool  # a formula reading it, with its guards, reads sensitive data (ruling 7)
    null_test: bool  # "is there" also tests `!= null`: it may be null, is untyped, or is only null (ruling 6)


@dataclass(frozen=True)
class Entry:
    path: str
    parent: str | None
    name: str
    root: Root
    step: str | None  # the step it comes from: a step's output or error, a loop's item
    types: tuple[str, ...]  # the JSON types it may have, sorted; () when any value
    format: str | None
    missing: bool
    nullable: bool
    sensitive: bool  # a reference to it holds sensitive data (engine 2b spec §4.1)
    nameable: bool  # a reference can name it; false for a key like `ap-name`, shown disabled
    children: bool
    formula: FormulaUse | None  # None when CEL can't select one of its fields (`in`, `null`, …), or `problem` is set
    problem: Diagnostic | None = None  # why reading it here is refused, as validation says it (`vars.unassigned`)


@dataclass(frozen=True)
class Scope:
    entries: tuple[Entry, ...] = ()
    more: bool = False  # some children past MAX_CHILDREN, or a search past its bounds
    problem: Diagnostic | None = None  # `at`: why the field can't read the path, as validation says it
    unavailable: str | None = None  # why there's no scope at all


def scope(
    graph: Graph,
    ctx: ValidationContext,
    node: uuid.UUID,
    field: str,
    *,
    under: str | None = None,
    at: str | None = None,
    find: str | None = None,
) -> Scope:
    a = analyze(graph, ctx)
    if a.structure is None or a.validator is None:
        return Scope(unavailable=NO_ANALYSIS)
    if node not in a.structure.nodes:
        return Scope(unavailable=NO_STEP)
    reader = _Reader(a, node, field)
    if at is not None:
        return reader.at(at)
    if under is not None:
        return reader.under(under)
    if find is not None:
        return reader.find(find)
    return reader.tops()


def _head(p: RefPath) -> str:
    """The part of a reference before its fields: `steps.k.output`, `vars.n`, `loops.k.item`, `run.now`, `trigger`."""
    if p.root in ("steps", "loops"):
        return f"{p.root}.{p.name}.{p.section}"
    if p.root == "vars":
        return f"vars.{p.name}"
    if p.root == "run":
        return f"run.{p.section}"
    return p.root


def _format(schema: Any) -> str | None:
    """The format the value surely has: within a way, the one its schemas declare (all of them apply); across ways,
    only one every way shares. Two formats in a way, or a way without one, leave nothing sure (the review of
    milestone 1: a nullable or conjoined date-time keeps its format)."""
    unfolded = alternatives(schema, schema) if schema is not None else None
    if unfolded is None or not unfolded[0]:
        return None
    shared: set[str] = set()
    for way in unfolded[0]:
        formats = {part["format"] for part in way if isinstance(part.get("format"), str)}
        if len(formats) != 1:
            return None
        shared |= formats
    return shared.pop() if len(shared) == 1 else None


def _split(p: RefPath) -> tuple[str | None, str]:
    """A path's parent and the name it shows: `trigger.events[0]` is `[0]` under `trigger.events`."""
    if not p.rest:
        return None, p.text
    last = p.rest[-1]
    shown = f"[{last}]" if isinstance(last, int) else last
    return p.text[: len(p.text) - len(shown) - (0 if isinstance(last, int) else 1)], shown


class _Reader:
    def __init__(self, a: Analysis, node: uuid.UUID, field: str) -> None:
        if a.structure is None or a.validator is None:
            raise ValueError("no analysis")
        self.s, self.v = a.structure, a.validator
        self.site = site_of(self.s, node, field)

    # ---- resolution -----------------------------------------------------------------------------------------

    def resolve(self, text: str) -> tuple[RefPath, Resolved] | None:
        try:
            p = parse_ref(text)
        except RefSyntaxError:
            return None
        r = self.v._resolve(self.site, p, report=False)
        return (p, r) if r is not None else None

    def roots(self) -> Iterator[str]:
        yield "trigger"
        for n_id in self.s.topo:
            key = self.s.nodes[n_id].key
            for section in ("output", "error"):
                if self.resolve(f"steps.{key}.{section}") is not None:
                    yield f"steps.{key}.{section}"
        for name in self.v.vars:
            if NAME.fullmatch(name):
                yield f"vars.{name}"
        if self.site.item_node is not None:
            yield from ("item", "index")
        for loop in self.s.chain(self.site.region):
            if loop is not None and loop != self.site.item_node and self.s.specs[loop].ref == C.LOOP:
                key = self.s.nodes[loop].key
                yield from (f"loops.{key}.item", f"loops.{key}.index")
        yield from ("run.id", "run.started_at", "run.now")

    # ---- entries --------------------------------------------------------------------------------------------

    def reported(self, p: RefPath) -> tuple[Resolved | None, list[Diagnostic]]:
        """The resolver's answer and what it reports (`vars.unassigned`, `ref.unknown_step`, …), leaving none behind."""
        mark = len(self.v.diags)
        r = self.v._resolve(self.site, p)
        problems = self.v.diags[mark:]
        del self.v.diags[mark:]
        return r, problems

    def entry(self, text: str) -> Entry | None:
        try:
            p = parse_ref(text)
        except RefSyntaxError:
            return None
        r, problems = self.reported(p)
        if r is None:
            return None
        parent, name = _split(p)
        types = json_types(r.schema)
        return Entry(
            path=text,
            parent=parent,
            name=name,
            root=p.root,  # type: ignore[arg-type]  # parse_ref gives one of Root's values
            step=self._step(p),
            types=tuple(sorted(types)) if types is not None and types <= JSON_TYPES else (),
            format=_format(r.schema),
            missing=r.missing,
            nullable=r.nullable,
            sensitive=r.taint.tainted,
            nameable=True,
            children=bool(self.child_names(r.schema)),
            formula=None if problems else self.formula(p),
            problem=problems[0] if problems else None,
        )

    def _step(self, p: RefPath) -> str | None:
        if p.root in ("steps", "loops") and p.name in self.s.by_key:
            return str(self.s.by_key[str(p.name)])
        return None

    def child_names(self, schema: Any) -> list[str | int]:
        if schema is None:
            return []
        unfolded = alternatives(schema, schema)
        if unfolded is None:
            return []
        names: dict[str | int, None] = {}
        for way in unfolded[0]:
            for part in way:
                props = part.get("properties")
                if isinstance(props, dict):
                    names.update(dict.fromkeys(k for k in props if isinstance(k, str)))
                items = part.get("items")
                if isinstance(items, dict) and items:
                    names[0] = None
        return list(names)

    def child(self, parent: str, name: str | int) -> Entry | None:
        if isinstance(name, int):
            text = f"{parent}[{name}]"
        elif NAME.fullmatch(name):
            text = f"{parent}.{name}"
        else:
            return self.unnameable(parent, name)
        if len(text) > MAX_REF_LENGTH:
            return self.unnameable(parent, name if isinstance(name, str) else f"[{name}]")
        return self.entry(text)

    def unnameable(self, parent: str, name: str) -> Entry | None:
        """A key a reference can't name (4c-2a ruling 5): shown, disabled, typed as its schema says."""
        found = self.resolve(parent)
        if found is None:
            return None
        p, r = found
        try:
            types = json_types(navigate(r.schema, [name]).schema) if r.schema is not None else None
        except PathError:
            types = None
        return Entry(
            path=f"{parent}.{name}", parent=parent, name=name, root=p.root,  # type: ignore[arg-type]
            step=self._step(p), types=tuple(sorted(types)) if types is not None and types <= JSON_TYPES else (),
            format=None, missing=True, nullable=False, sensitive=r.taint.tainted, nameable=False, children=False,
            formula=None,
        )  # fmt: skip

    # ---- the four questions ---------------------------------------------------------------------------------

    def tops(self) -> Scope:
        out: list[Entry] = []
        more = False
        for text in self.roots():
            top = self.entry(text)
            if top is None:
                continue
            out.append(top)
            names = self.child_names(self.resolve(text)[1].schema) if top.children else []  # type: ignore[index]
            more |= len(names) > MAX_CHILDREN
            out += [e for name in names[:MAX_CHILDREN] if (e := self.child(text, name)) is not None]
        return Scope(tuple(out), more=more)

    def under(self, text: str) -> Scope:
        found = self.resolve(text)
        if found is None:
            return Scope()
        names = self.child_names(found[1].schema)
        entries = [e for name in names[:MAX_CHILDREN] if (e := self.child(text, name)) is not None]
        return Scope(tuple(entries), more=len(names) > MAX_CHILDREN)

    def at(self, text: str) -> Scope:
        try:
            p = parse_ref(text)
        except RefSyntaxError as e:
            return Scope(problem=Diagnostic(code="value.syntax", message=f"`{text}`: {e}"))
        r, problems = self.reported(p)  # its problem is the validator's own
        if r is None:
            return Scope(problem=problems[0] if problems else None)
        entry = self.entry(text)
        return Scope((entry,) if entry is not None else (), problem=problems[0] if problems else None)

    def find(self, text: str) -> Scope:
        """Fields whose name holds `text`, breadth first. `more` says the search stopped short at one of its bounds
        (children past MAX_CHILDREN, fields below FIND_DEPTH, FIND_VISITS, FIND_FOUND) while something was left
        unsearched: never "nothing more" unless all of it was searched (the review of milestone 1)."""
        needle = text.casefold()
        found: list[Entry] = []
        visits = 0
        omitted = False
        queue: deque[tuple[str, int]] = deque((root, 0) for root in self.roots())
        while queue:
            if len(found) >= FIND_FOUND or visits >= FIND_VISITS:
                omitted = True  # the queue still holds fields to search
                break
            parent, depth = queue.popleft()
            resolved = self.resolve(parent)
            names = self.child_names(resolved[1].schema) if resolved is not None else []
            if not names:
                continue
            if depth >= FIND_DEPTH:
                omitted = True  # fields below the search's depth
                continue
            omitted |= len(names) > MAX_CHILDREN
            for name in names[:MAX_CHILDREN]:
                if len(found) >= FIND_FOUND or visits >= FIND_VISITS:
                    omitted = True  # this parent's other children
                    break
                visits += 1
                e = self.child(parent, name)
                if e is None:
                    continue
                if isinstance(name, str) and needle in name.casefold():
                    found.append(e)
                if e.nameable and e.children:
                    queue.append((e.path, depth + 1))
        return Scope(tuple(found), more=omitted)

    # ---- formulas -------------------------------------------------------------------------------------------

    def formula(self, p: RefPath) -> FormulaUse | None:
        """How a formula reads `p` safely (4c-2a rulings 6, 7). None when CEL can't select one of its fields."""
        if any(isinstance(seg, str) and seg in CEL_KEYWORDS for seg in p.rest):
            return None
        head = _head(p)
        found = self.resolve(head)
        if found is None:
            return None
        whole = found[1]
        guards: list[Guard] = []
        if p.root == "steps" and whole.missing:
            guards.append(Guard("present", head))  # the step may not have run
        schema, nullable, prefix = whole.schema, whole.nullable, head
        for seg in p.rest:
            if nullable:
                guards.append(Guard("not_null", prefix))
            types = json_types(schema)
            if isinstance(seg, int):
                if types != frozenset({"array"}):
                    guards.append(Guard("is_list", prefix))
                guards.append(Guard("min_size", prefix, seg))
                path = f"{prefix}[{seg}]"
            else:
                if types != frozenset({"object"}):
                    guards.append(Guard("is_map", prefix))
                path = f"{prefix}.{seg}"
            try:
                step = navigate(schema, [seg]) if schema is not None else Resolved(None, True, missing=True)
            except PathError:
                return None
            if isinstance(seg, str) and step.missing:
                guards.append(Guard("present", path))  # never on a list always there: it isn't missing
            schema, nullable, prefix = step.schema, step.nullable, path
        # `has(steps.k.output)` reads the run's shape (whether the step ran), never the output (cel_check's `shape`).
        reads = {
            p.text,
            *(g.path for g in guards if not (g.kind == "present" and g.path == head and p.root == "steps")),
        }
        sensitive = any(self.reads_sensitive(parse_ref(text)) for text in reads)
        types = json_types(whole.schema) if not p.rest else json_types(schema)
        null_test = nullable or types is None or types == frozenset({"null"})
        return FormulaUse(tuple(guards), sensitive, null_test)

    def reads_sensitive(self, p: RefPath) -> bool:
        """Whether a formula reading `p` reads sensitive data: CEL's chain stops at the first index, so through one it
        reads that list whole; a bare root is read whole (engine 2b spec §4.1)."""
        cut = next((i for i, seg in enumerate(p.rest) if isinstance(seg, int)), len(p.rest))
        if p.root in ("trigger", "item") and cut == 0:
            return self.v._root_tainted(self.site, p.root)
        prefix = _head(p) + "".join(f".{seg}" for seg in p.rest[:cut])
        return self.v._taint_of(self.site, parse_ref(prefix)).tainted
