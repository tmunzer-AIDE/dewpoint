# SPDX-License-Identifier: Apache-2.0
"""The CEL runtime adapter (spec §5.1). This is the only module that imports cel-expr-python.

Four operations: parse, compile with a typed environment (giving the checked AST), evaluate, and report errors.
Checked ASTs are decoded with the vendored cel-spec protos. The runtime's own serialization is not deterministic
(protobuf map order), so nothing hashes or stores it: callers keep the decoded message or facts derived from it."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cel_expr_python import cel as _cel
from google.protobuf import any_pb2

from dewpoint.engine.cel import functions, types
from dewpoint.engine.cel.proto import checked_pb2, syntax_pb2

_PROBLEM = re.compile(r"ERROR: <input>:(\d+):(\d+): ([^\n]*)")


class CompileError(ValueError):
    """Parse or type-check failure. `problems` holds the checker's messages, first one first."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(problems[0] if problems else "invalid expression")
        self.problems = problems


@dataclass(frozen=True)
class Compiled:
    checked: checked_pb2.CheckedExpr
    program: Any  # the runtime's Expression; evaluate() is its only use


@dataclass(frozen=True)
class RawResult:
    """What the runtime returned. kind: `value` (plain Python value, runtime type name), `error` (a CEL error value)
    or `aborted` (the runtime raised, e.g. the iteration budget)."""

    kind: str
    value: Any = None
    type_name: str = ""
    message: str = ""


def _problems(error: Exception) -> list[str]:
    text = str(error)
    found = [f"{line}:{col}: {msg}" for line, col, msg in _PROBLEM.findall(text)]
    return found or [text.splitlines()[0] if text else type(error).__name__]


def _type(signature: str) -> Any:
    if signature not in types.SIGNATURES:
        raise ValueError(f"unsupported CEL type {signature!r}")
    return _cel.Type(signature)


def _functions() -> list[Any]:
    return [
        _cel.FunctionDecl(
            f.name,
            [_cel.Overload(o.id, _type(o.result), [_type(p) for p in o.params], impl=o.impl) for o in f.overloads],
        )
        for f in functions.FUNCTIONS
    ]


def _env(declarations: Mapping[str, str]) -> Any:
    return _cel.NewEnv(variables={name: _type(sig) for name, sig in declarations.items()}, functions=_functions())


def _unpack(serialized: bytes, message: Any) -> Any:
    wrapper = any_pb2.Any()
    wrapper.ParseFromString(serialized)
    if not wrapper.Unpack(message):
        raise CompileError([f"unexpected AST payload {wrapper.type_url}"])
    return message


def parse(expr: str) -> syntax_pb2.ParsedExpr:
    """Syntax only: no declarations, no type check. Node ids match the checked AST of the same text."""
    try:
        compiled = _env({}).compile(expr, disable_check=True)
    except RuntimeError as e:
        raise CompileError(_problems(e)) from None
    parsed: syntax_pb2.ParsedExpr = _unpack(compiled.serialize(), syntax_pb2.ParsedExpr())
    return parsed


def compile_checked(expr: str, declarations: Mapping[str, str]) -> Compiled:
    try:
        program = _env(declarations).compile(expr)
    except RuntimeError as e:
        raise CompileError(_problems(e)) from None
    checked: checked_pb2.CheckedExpr = _unpack(program.serialize(), checked_pb2.CheckedExpr())
    return Compiled(checked, program)


def evaluate(compiled: Compiled, bindings: Mapping[str, Any]) -> RawResult:
    try:
        value = compiled.program.eval(data=dict(bindings))
    except RuntimeError as e:  # the runtime aborts (e.g. "Iteration budget exceeded") instead of returning an error
        return RawResult("aborted", message=str(e))
    type_name = value.type().name()
    if type_name == "ERROR":
        return RawResult("error", message=str(value.plain_value()))
    return RawResult("value", value.plain_value(), type_name)
