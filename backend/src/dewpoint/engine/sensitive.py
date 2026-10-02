# SPDX-License-Identifier: Apache-2.0
"""Where a JSON Schema puts sensitive values (`x-sensitive`), read without running anything on the data: behind local
`$ref`s, in any branch of `anyOf`, `oneOf` or `allOf` (sensitive in one branch, sensitive in all), under any
`patternProperties` schema of its object (no regex runs: over-marking, never a leak), at a tuple's position
(`prefixItems`); a map whose keys are sensitive (`propertyNames`) is sensitive whole.

The projection redacts with it (`engine.runtime.projection`), and publish checks literals with it (§3.8). Taint and
claiming (engine 2b spec §3.5, §4.1) go further: a position the schema doesn't declare is sensitive too, since unknown
counts as sensitive (`engine.taint`)."""

from collections.abc import Collection, Mapping
from typing import Any

from dewpoint.engine.handles import escape

SENSITIVE = "x-sensitive"
SECRET_INDEX_LIMIT = "secret_index_limit"  # noqa: S105 - a code: as core.claims.secret_index's (a test keeps them equal)
MIN_SECRET = 4  # a secret's characters, at least: shorter values would match ordinary text ("1", "yes") everywhere
_MAX_DEPTH = 64  # a schema that refers to itself ends here


def resolve(root: Mapping[str, Any], ref: str) -> Any:
    """A local JSON pointer (`#/$defs/Name`); anything else resolves to nothing (schemas are local-only, spec §4.1)."""
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        node = node.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(node, Mapping) else None
    return node


def expand(schema: Any, root: Mapping[str, Any], depth: int = 0) -> list[Mapping[str, Any]]:
    """`schema` and everything it stands for: its `$ref` followed, its `anyOf`/`oneOf`/`allOf` branches expanded."""
    if not isinstance(schema, Mapping) or depth > _MAX_DEPTH:
        return []
    out: list[Mapping[str, Any]] = [schema]
    ref = schema.get("$ref")
    if isinstance(ref, str):
        out += expand(resolve(root, ref), root, depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        subs = schema.get(key)
        for sub in subs if isinstance(subs, list) else ():
            out += expand(sub, root, depth + 1)
    return out


def patterns(branch: Mapping[str, Any]) -> list[Any]:
    """Every `patternProperties` schema, matched or not: no regex runs on data in the workflow, so a sensitive
    pattern redacts every key's value in its object, declared keys included (over-redaction, never a leak)."""
    patterns = branch.get("patternProperties")
    return list(patterns.values()) if isinstance(patterns, Mapping) else []


def map_values(branches: list[Mapping[str, Any]]) -> list[Any]:
    """The schemas that may govern an undeclared key's value: `additionalProperties` and every pattern."""
    out: list[Any] = []
    for b in branches:
        if isinstance(b.get("additionalProperties"), Mapping):
            out.append(b["additionalProperties"])
        out.extend(patterns(b))
    return out


def children(branches: list[Mapping[str, Any]], key: str) -> list[Any]:
    """The schemas that may govern `key`'s value. JSON Schema applies a declared property and every matching pattern
    together; `additionalProperties` only to keys neither covers."""
    out: list[Any] = []
    for b in branches:
        props = b.get("properties")
        if isinstance(props, Mapping) and key in props:
            out += [props[key], *patterns(b)]
        else:
            out += map_values([b])
    return out


def elements(branches: list[Mapping[str, Any]], index: int) -> list[Any]:
    """The schemas that may govern a list's element `index`: its tuple position (`prefixItems`), and `items`."""
    out: list[Any] = [b["items"] for b in branches if isinstance(b.get("items"), Mapping)]
    for b in branches:
        prefix = b.get("prefixItems")
        if isinstance(prefix, list) and index < len(prefix):
            out.append(prefix[index])
    return out


def keys_sensitive(branches: list[Mapping[str, Any]], root: Mapping[str, Any]) -> bool:
    names = [b["propertyNames"] for b in branches if isinstance(b.get("propertyNames"), Mapping)]
    return any(n.get(SENSITIVE) is True for s in names for n in expand(s, root))


def _holes_only(value: Any, pointer: str, holes: Collection[str]) -> bool:
    """Whether everything at `pointer` stands in for a hole: nothing there is written as a literal."""
    if pointer in holes:
        return True
    if isinstance(value, dict) and value:
        return all(_holes_only(v, pointer + "/" + escape(k), holes) for k, v in value.items())
    if isinstance(value, list) and value:
        return all(_holes_only(v, pointer + "/" + str(i), holes) for i, v in enumerate(value))
    return False


def _marked(
    value: Any, schemas: list[Any], root: Mapping[str, Any], pointer: str, out: list[str], holes: Collection[str]
) -> None:
    if pointer in holes:
        return
    branches = [b for s in schemas for b in expand(s, root)]
    if any(b.get(SENSITIVE) is True for b in branches) or (isinstance(value, dict) and keys_sensitive(branches, root)):
        if not _holes_only(value, pointer, holes):
            out.append(pointer)
    elif isinstance(value, dict):
        for key, child in value.items():
            _marked(child, children(branches, key), root, pointer + "/" + escape(key), out, holes)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _marked(child, elements(branches, index), root, pointer + "/" + str(index), out, holes)


def marked_positions(
    value: Any, schema: Mapping[str, Any], root: Mapping[str, Any] | None = None, holes: Collection[str] = ()
) -> list[str]:
    """The pointers of `value`'s parts, null and empty ones included, that the schema marks sensitive (`x-sensitive`,
    or a map whose keys are), in document order. An undeclared key follows the schemas that govern it, and isn't
    sensitive for that alone: this is what a workflow author wrote, checked at publish (§3.8). `root` resolves `$ref`s
    (the schema by default). `holes`: pointers where no literal stands (a value envelope, checked where it's
    resolved), skipped, and so is a marked part made only of them."""
    out: list[str] = []
    _marked(value, [schema], root if root is not None else schema, "", out, holes)
    return out


def is_marked(schema: Mapping[str, Any], path: tuple[str | int, ...], root: Mapping[str, Any] | None = None) -> bool:
    """Whether the position at `path` lies at or under a part the schema marks sensitive."""
    resolve_in = root if root is not None else schema
    schemas: list[Any] = [schema]
    for depth in range(len(path) + 1):
        branches = [b for s in schemas for b in expand(s, resolve_in)]
        if any(b.get(SENSITIVE) is True for b in branches) or (
            depth < len(path) and keys_sensitive(branches, resolve_in)
        ):
            return True
        if depth == len(path):
            return False
        part = path[depth]
        schemas = elements(branches, part) if isinstance(part, int) else children(branches, part)
    return False
