# SPDX-License-Identifier: Apache-2.0
"""The vendored cel-spec protos are the pinned ones (spec §5.5): git blob hashes of the upstream files at
google/cel-spec commit b0b10835ca4d31a1a32b86e2e25d66bb9dd8f042."""

import hashlib
from pathlib import Path

import dewpoint.engine.cel.proto as proto_pkg
from dewpoint.engine.cel.proto import checked_pb2, syntax_pb2

PINNED = {
    "checked.proto": "0105b93adafadef166846f03710bc44cdc7f337f",
    "syntax.proto": "00635e664cdb8eaa3bacfc4fc169ceb291b3ccc7",
}


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def test_vendored_proto_sources_match_the_pinned_commit() -> None:
    here = Path(proto_pkg.__file__).parent
    assert {name: _git_blob((here / name).read_bytes()) for name in PINNED} == PINNED


def test_generated_modules_describe_the_same_files() -> None:
    assert checked_pb2.DESCRIPTOR.name == "cel/expr/checked.proto"
    assert syntax_pb2.DESCRIPTOR.name == "cel/expr/syntax.proto"
    assert checked_pb2.CheckedExpr.DESCRIPTOR.full_name == "cel.expr.CheckedExpr"
