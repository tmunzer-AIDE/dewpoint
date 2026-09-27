# SPDX-License-Identifier: Apache-2.0
"""CEL values at publish time (spec §5.3, §5.5, §5.10): typed environment, references, guards, result type and
classification. The validator supplies scope through `CelContext`; this module never reads the graph itself."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from dewpoint.engine.cel import ast, classify, functions, guards, record, runtime
from dewpoint.engine.cel import types as T
from dewpoint.engine.graph.diagnostics import Severity
from dewpoint.engine.graph.schemas import Resolved, compatible, describe, element_schema, json_types
from dewpoint.engine.graph.values import RefPath, RefSyntaxError, parse_ref

ROOTS = ("trigger", "steps", "vars", "loops", "run")
ITEM_ROOTS = ("item", "index")
_UNDECLARED = re.compile(r"undeclared reference to '([^']+)'")
_ELEMENT = {"object": T.MAP, "string": T.STRING, "boolean": T.BOOL, "array": T.LIST}


class CelContext(Protocol):
    has_item: bool  # `item` and `index` exist here (a loop body, or a filter predicate)

    def resolve(self, path: RefPath, *, report: bool) -> Resolved | None: ...

    def optional_fields(self, path: RefPath) -> tuple[int, ...]:
        """Positions in `path.rest` of fields its schema declares but doesn't require."""
        ...

    def error(self, code: str, message: str, *, fix: str | None = None, severity: Severity = "error") -> None: ...


@dataclass(frozen=True)
class CelResult:
    resolved: Resolved | None  # the value's type, for downstream checks
    record: record.ExpressionRecord | None  # None when the expression has errors


def _element_signature(schema: Mapping[str, Any] | None) -> str:
    types = json_types(element_schema(schema))
    return _ELEMENT.get(next(iter(types)), T.DYN) if types is not None and len(types) == 1 else T.DYN


def _typed(path: ast.Path, ctx: CelContext) -> str | None:
    """The list signature for an always-available array path, or None."""
    try:
        ref = parse_ref(".".join(path))
    except RefSyntaxError:
        return None
    r = ctx.resolve(ref, report=False)
    if r is None or r.conditional or json_types(r.schema) != frozenset({"array"}):
        return None
    return T.list_of(_element_signature(r.schema))


def declarations(parsed: ast.Expr, ctx: CelContext) -> dict[str, str]:
    decls = dict.fromkeys(ROOTS, T.MAP)
    if ctx.has_item:
        decls.update(item=T.DYN, index=T.INT)
    for chain in ast.chains(parsed):
        fields = chain.path[:-1] if chain.presence else chain.path  # a has() test never needs a typed field
        first = 0 if chain.root == "item" else 1
        for end in range(first, len(fields)):
            candidate = fields[: end + 1]
            if chain.root in decls and (sig := _typed(candidate, ctx)) is not None:
                decls[".".join(candidate)] = sig
    return decls


def _compile_problems(e: runtime.CompileError, parsed: ast.Expr | None, ctx: CelContext) -> None:
    called = ast.called_functions(parsed) if parsed is not None else set()
    seen: set[str] = set()
    for problem in e.problems:
        m = _UNDECLARED.search(problem)
        name = m.group(1) if m else None
        if name in seen:
            continue
        if name is not None:
            seen.add(name)
        if name in ITEM_ROOTS:
            ctx.error("ref.loop_outside", "`item` and `index` exist only inside a loop body or a filter predicate.")
        elif name is not None and name in called:
            available = ", ".join(sorted(functions.NAMES))
            ctx.error("cel.unknown_function", f"`{name}` isn't available. Available functions: {available}.")
        elif name is not None:
            ctx.error(
                "cel.unknown_name",
                f"`{name}` isn't defined here.",
                fix="Expressions start with trigger, steps, vars, item, index, loops or run.",
            )
        elif "reserved identifier: loop" in problem:
            ctx.error(
                "cel.unknown_name",
                "`loop` is a reserved word in CEL.",
                fix="Write `item` and `index` for the innermost loop, `loops.<key>.item` for an enclosing one.",
            )
        else:
            ctx.error("cel.invalid", f"This expression isn't valid: {problem}")


def _diagnostic_path(path: ast.Path) -> str | None:
    """The reference to check for a chain, or None for a bare root (nothing to check)."""
    root = path[0]
    if len(path) == 1:
        return ".".join(path) if root in ITEM_ROOTS else None
    if root == "steps" and len(path) == 2:
        return f"steps.{path[1]}.output"  # the step itself: exists, in scope, upstream
    if root == "loops" and len(path) == 2:
        return f"loops.{path[1]}.index"
    return ".".join(path)


def _optional_prefixes(chain: ast.Chain, ref: RefPath, ctx: CelContext) -> list[ast.Path]:
    """Every prefix of what the chain reads that ends at a schema-declared optional field. A presence test reads its
    operand, not the field it tests."""
    offset = len(chain.path) - len(ref.rest)
    read = len(chain.path) - (1 if chain.presence else 0)
    return [chain.path[: offset + i + 1] for i in ctx.optional_fields(ref) if offset + i + 1 <= read]


_STRUCTURAL = {"steps": ("a step", "`steps.<key>.output`"), "loops": ("a loop", "`loops.<key>.item`")}


def _structural_keys(checked: Any, ctx: CelContext) -> bool:
    """`steps` and `loops` keys are the graph's own: publish checks them (exists, in scope, upstream, guarded), so a
    key chosen at run time, or one no step could have, is refused. Other data may be indexed freely."""
    ok = True
    for path in ast.keyed_chains(checked.expr):
        if path[0] in _STRUCTURAL and len(path) <= 2:
            what, written = _STRUCTURAL[path[0]]
            ok = False
            ctx.error(
                "cel.bad_path",
                f"`{'.'.join(path)}[…]` chooses {what if len(path) == 1 else 'its field'} at run time, so publish "
                "can't check it.",
                fix=f"Name it: {written}.",
            )
    return ok


def _references(checked: Any, ctx: CelContext) -> bool:
    ok = _structural_keys(checked, ctx)
    facts = guards.facts_at(checked.expr)
    reported: set[ast.Path] = set()
    for chain in ast.chains(checked.expr):
        text = _diagnostic_path(chain.path)
        if text is None:
            continue
        try:
            ref = parse_ref(text)
        except RefSyntaxError as e:
            ctx.error("cel.bad_path", f"`{'.'.join(chain.path)}`: {e}.")
            ok = False
            continue
        if ctx.resolve(ref, report=True) is None:
            ok = False
            continue
        known = facts[chain.expr_id]
        read = chain.path[:-1] if chain.presence else chain.path
        section = read[:3]
        if chain.root == "steps" and len(section) == 3 and section not in known and section not in reported:
            availability = ctx.resolve(parse_ref(".".join(section)), report=False)
            if availability is not None and availability.conditional:
                reported.add(section)
                ok = False
                ctx.error(
                    "cel.conditional_ref",
                    f"`steps.{section[1]}` may not have run on every path, so `{'.'.join(section)}` may be missing.",
                    fix=f"Guard it with `has({'.'.join(section)})`.",
                )
        for optional in _optional_prefixes(chain, ref, ctx):
            if optional in known or optional in reported:
                continue
            reported.add(optional)
            ok = False
            ctx.error(
                "cel.conditional_ref",
                f"`{'.'.join(optional)}` is optional in its schema, so it may be missing.",
                fix=f"Guard it with `has({'.'.join(optional)})`.",
            )
    return ok


def _result(checked: Any, target: Mapping[str, Any] | None, ctx: CelContext) -> tuple[Resolved | None, bool]:
    types = ast.json_types(checked.type_map.get(checked.expr.id))
    if types == ast.NON_JSON:
        ctx.error("cel.non_json_result", "This expression gives a value JSON can't hold (bytes or a type).")
        return None, False
    schema: dict[str, Any] | None = None
    if types is not None:
        ordered = sorted(types)
        schema = {"type": ordered[0] if len(ordered) == 1 else ordered}
    if target is not None and not compatible(schema, target):
        ctx.error(
            "cel.type_mismatch", f"This expression gives {describe(schema)}, but this field expects {describe(target)}."
        )
        return Resolved(schema, False), False
    return Resolved(schema, False), True


def check(expr: str, target: Mapping[str, Any] | None, ctx: CelContext, *, node: str | None, field: str) -> CelResult:
    try:
        parsed = runtime.parse(expr)
    except runtime.CompileError as e:
        _compile_problems(e, None, ctx)
        return CelResult(None, None)
    decls = declarations(parsed.expr, ctx)
    collapsed = sorted({".".join(c.path) for c in ast.chains(parsed.expr) if c.presence and ".".join(c.path) in decls})
    for name in collapsed:  # the checker would turn has(<typed path>) into the list itself (tests/engine/cel)
        ctx.error(
            "cel.has_on_typed_path",
            f"`{name}` always exists here, and `has()` on it gives the list, not true.",
            fix="Remove the `has()` test.",
        )
    if collapsed:
        return CelResult(None, None)
    try:
        checked = runtime.compile_checked(expr, decls).checked
    except runtime.CompileError as e:
        _compile_problems(e, parsed.expr, ctx)
        return CelResult(None, None)
    ok = True
    for p in classify.order_problems(checked):
        ok = False
        ctx.error(p.code, p.message, fix=p.fix)
    ok = _references(checked, ctx) and ok
    resolved, typed_ok = _result(checked, target, ctx)
    if not (ok and typed_ok):
        return CelResult(resolved, None)
    c = classify.classify(expr, checked)
    if ast.comprehension_depth(checked.expr) > 1 or (c.iterations or 0) > classify.MAX_LOCAL_ITERATIONS:
        ctx.error(
            "cel.iteration_budget",
            "An expression can iterate fewer than 10,000 times; with large inputs this one may stop there.",
            fix="For large lists, use a Loop or Filter node.",
            severity="warning",
        )
    chains = ast.chains(checked.expr)
    return CelResult(
        resolved,
        record.ExpressionRecord(
            node=node,
            field=field,
            expr=expr,
            declarations=decls,
            idents=tuple(ast.global_idents(checked.expr)),
            projections=record.projections(chains, decls),
            mode=c.mode,
            reason=c.reason,
            iterations=c.iterations,
            bytes=c.bytes,
            work=c.work,
        ),
    )
