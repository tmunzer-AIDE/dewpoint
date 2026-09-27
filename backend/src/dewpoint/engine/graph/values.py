# SPDX-License-Identifier: Apache-2.0
"""Value envelopes inside node configs, and reference paths (spec §4.3).

Any JSON object of the form {"$value": {...}} is an envelope; everything else in a config is literal JSON."""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

ENVELOPE = "$value"
MAX_REF_LENGTH = 512
MAX_TEMPLATE_PARTS = 100
MAX_TEXT = 4096
MAX_CEL = 16_384  # spec §5.2: longer expressions are rejected
CEL_KEYWORDS = frozenset({"in", "true", "false", "null"})  # CEL can't select these as fields: never keys or names

Pointer = tuple[str | int, ...]
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INDEX = re.compile(r"\[(0|[1-9][0-9]{0,5})\]")
_ALLOWED_KEYS = {
    "literal": {"kind", "value"},
    "ref": {"kind", "path", "default"},
    "template": {"kind", "parts"},
    "cel": {"kind", "expr"},
}


class RefSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class RefPath:
    text: str
    root: str  # trigger | steps | vars | item | index | loops | run
    name: str | None  # step key, variable name or loop key
    section: str | None  # output | error | item | index | id | started_at | now
    rest: tuple[str | int, ...]


def _tokens(text: str) -> list[str | int]:
    first = _IDENT.match(text)
    if first is None:
        raise RefSyntaxError("a reference starts with a name")
    out: list[str | int] = [first.group()]
    pos = first.end()
    while pos < len(text):
        if text[pos] == ".":
            m = _IDENT.match(text, pos + 1)
            if m is None:
                raise RefSyntaxError("expected a field name after `.`")
            out.append(m.group())
        else:
            m = _INDEX.match(text, pos)
            if m is None:
                raise RefSyntaxError("expected `.name` or `[n]`")
            out.append(int(m.group(1)))
        pos = m.end()
    return out


def _name(tokens: list[str | int], i: int, what: str) -> str:
    value = tokens[i] if i < len(tokens) else None
    if not isinstance(value, str):
        raise RefSyntaxError(f"expected {what}")
    return value


def _loop_ref(text: str, root: str, name: str | None, section: str, rest: list[str | int]) -> RefPath:
    if section not in ("item", "index"):
        raise RefSyntaxError("a loop reference reads `item` or `index`")
    if section == "index" and rest:
        raise RefSyntaxError("`index` has no fields")
    return RefPath(text, root, name, section, tuple(rest))


def parse_ref(text: Any) -> RefPath:
    if not isinstance(text, str) or not text or len(text) > MAX_REF_LENGTH:
        raise RefSyntaxError("a reference must be a non-empty path")
    t = _tokens(text)
    root = t[0]
    if root == "trigger":
        return RefPath(text, "trigger", None, None, tuple(t[1:]))
    if root == "steps":
        name, section = _name(t, 1, "a step key"), _name(t, 2, "`output` or `error`")
        rest = tuple(t[3:])
        if section not in ("output", "error"):
            raise RefSyntaxError("after `steps.<key>` comes `output` or `error`")
        if section == "error" and (len(rest) > 1 or (rest and rest[0] not in ("code", "message", "attempt"))):
            raise RefSyntaxError("`error` has `code`, `message` and `attempt`")
        return RefPath(text, "steps", name, section, rest)
    if root == "vars":
        return RefPath(text, "vars", _name(t, 1, "a variable name"), None, tuple(t[2:]))
    if root in ("item", "index"):  # the innermost loop's item, or the filter item in a predicate
        return _loop_ref(text, root, None, root, t[1:])
    if root == "loop":
        raise RefSyntaxError("`loop.item` is written `item`, and `loop.index` is `index`")
    if root == "loops":
        return _loop_ref(text, "loops", _name(t, 1, "a loop key"), _name(t, 2, "`item` or `index`"), t[3:])
    if root == "run":
        section = _name(t, 1, "`id`, `started_at` or `now`")
        if section not in ("id", "started_at", "now") or len(t) > 2:
            raise RefSyntaxError("`run` has `id`, `started_at` and `now`")
        return RefPath(text, "run", None, section, ())
    raise RefSyntaxError(f"references start with trigger, steps, vars, item, index, loops or run, not `{root}`")


@dataclass(frozen=True)
class LiteralValue:
    kind: ClassVar[str] = "literal"
    value: Any


@dataclass(frozen=True)
class RefValue:
    kind: ClassVar[str] = "ref"
    path: RefPath
    default: Any = None
    has_default: bool = False


@dataclass(frozen=True)
class TemplateRef:
    path: RefPath
    default: str | None = None


@dataclass(frozen=True)
class TemplateValue:
    kind: ClassVar[str] = "template"
    parts: tuple[str | TemplateRef, ...]


@dataclass(frozen=True)
class CelValue:
    kind: ClassVar[str] = "cel"
    expr: str


Value = LiteralValue | RefValue | TemplateValue | CelValue


@dataclass(frozen=True)
class ValueSyntaxError:
    """Not an exception: iter_values yields it in place of a value, so every problem gets reported."""

    message: str


def is_envelope(obj: Any) -> bool:
    return isinstance(obj, Mapping) and ENVELOPE in obj


def _template_part(part: Any) -> str | TemplateRef:
    if isinstance(part, Mapping) and set(part) == {"text"} and isinstance(part["text"], str):
        if len(part["text"]) > MAX_TEXT:
            raise ValueError(f"template text is limited to {MAX_TEXT} characters")
        return part["text"]
    if isinstance(part, Mapping) and "ref" in part and set(part) <= {"ref", "default"}:
        default = part.get("default")
        if default is not None and not isinstance(default, str):
            raise ValueError("a template default must be text")
        return TemplateRef(parse_ref(part["ref"]), default)
    raise ValueError("each template part is {text} or {ref, default?}")


def parse_envelope(body: Any) -> Value:
    if not isinstance(body, Mapping):
        raise ValueError("`$value` must be an object")
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in _ALLOWED_KEYS:  # type first: a list or dict is unhashable
        raise ValueError("`kind` must be literal, ref, template or cel")
    extra = set(body) - _ALLOWED_KEYS[kind]
    if extra:
        raise ValueError(f"unexpected keys: {', '.join(sorted(extra))}")
    if kind == "literal":
        if "value" not in body:
            raise ValueError("a literal needs `value`")
        return LiteralValue(body["value"])
    if kind == "ref":
        return RefValue(parse_ref(body.get("path")), body.get("default"), "default" in body)
    if kind == "template":
        parts = body.get("parts")
        if not isinstance(parts, list) or not parts or len(parts) > MAX_TEMPLATE_PARTS:
            raise ValueError(f"a template has 1 to {MAX_TEMPLATE_PARTS} parts")
        return TemplateValue(tuple(_template_part(p) for p in parts))
    expr = body.get("expr")
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("`expr` must be non-empty text")
    if len(expr) > MAX_CEL:
        raise ValueError(f"expressions are limited to {MAX_CEL} characters")
    return CelValue(expr)


def iter_values(config: Any, base: Pointer = ()) -> Iterator[tuple[Pointer, Value | ValueSyntaxError]]:
    """Every envelope in `config`, in a deterministic order (object keys sorted). Literals are not yielded."""
    if isinstance(config, Mapping):
        if ENVELOPE in config:
            if len(config) != 1:
                yield base, ValueSyntaxError("an object with `$value` can't have other keys")
                return
            try:
                yield base, parse_envelope(config[ENVELOPE])
            except ValueError as e:
                yield base, ValueSyntaxError(str(e))
            return
        for key in sorted(config):
            yield from iter_values(config[key], (*base, key))
    elif isinstance(config, list):
        for index, item in enumerate(config):
            yield from iter_values(item, (*base, index))


def strip_values(config: Any) -> tuple[Any, list[Pointer]]:
    """`config` with every envelope replaced by null, plus the envelopes' pointers."""
    pointers = [p for p, _ in iter_values(config)]

    def walk(obj: Any) -> Any:
        if isinstance(obj, Mapping):
            return None if ENVELOPE in obj else {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        return obj

    return walk(config), pointers


def pointer_str(pointer: Pointer) -> str:
    return "".join("/" + str(seg).replace("~", "~0").replace("/", "~1") for seg in pointer)
