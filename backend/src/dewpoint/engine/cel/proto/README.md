# Vendored cel-spec protos

The CEL classifier reads checked ASTs (`google.protobuf.Any` wrapping `cel.expr.CheckedExpr`) with these messages
(spec §5.5). They are vendored, not installed, so the decoded format can only change on purpose.

| File | Source | Git blob |
|---|---|---|
| `checked.proto` | [google/cel-spec](https://github.com/google/cel-spec) `proto/cel/expr/checked.proto` at `b0b10835ca4d31a1a32b86e2e25d66bb9dd8f042` | `0105b93adafadef166846f03710bc44cdc7f337f` |
| `syntax.proto` | same commit, `proto/cel/expr/syntax.proto` | `00635e664cdb8eaa3bacfc4fc169ceb291b3ccc7` |

License: Apache-2.0 (the headers in the `.proto` files; the same license as Dewpoint). `tests/engine/cel/test_protos.py`
checks the blob hashes.

`*_pb2.py` and `*_pb2.pyi` are protoc output from grpcio-tools 1.84.0 (protobuf gencode 7.35.1). The only edit is the
import of `syntax_pb2` in `checked_pb2.py` and `checked_pb2.pyi`, from `cel.expr` to this package. To regenerate, from
`backend/`:

```bash
tmp=$(mktemp -d) && mkdir -p "$tmp/cel/expr" && cp src/dewpoint/engine/cel/proto/*.proto "$tmp/cel/expr/" && \
uvx --from grpcio-tools==1.84.0 python -m grpc_tools.protoc -I "$tmp" --python_out="$tmp" --pyi_out="$tmp" \
  cel/expr/syntax.proto cel/expr/checked.proto && \
cp "$tmp"/cel/expr/*_pb2.py* src/dewpoint/engine/cel/proto/ && \
sed -i.bak 's/^from cel\.expr import syntax_pb2/from dewpoint.engine.cel.proto import syntax_pb2/' \
  src/dewpoint/engine/cel/proto/checked_pb2.py src/dewpoint/engine/cel/proto/checked_pb2.pyi && \
rm src/dewpoint/engine/cel/proto/*.bak
```

A new runtime pin, a new protobuf major version or new protos is a new CEL profile (spec §5.1): run the §5.9 gates.
