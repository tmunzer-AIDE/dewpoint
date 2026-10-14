# cel-expr-python 0.1.3+dewpoint.1

A patched build of cel-expr-python 0.1.3, made by the Dewpoint project. It is not an upstream release.

## Source

- cel-python commit 3e369fe3dfd29ef2fcb3d8a63997e58f50e592ae (tag v0.1.3), https://github.com/cel-expr/cel-python
- plus `dewpoint-cel-0.1.3-backport.patch` (in this directory), sha256
  38c995fb5ae21354dfa6cb482fb4857e1872e7d7b9e7d67b44ec02748d1caf16

## Changes (Apache License 2.0, section 4(b))

The patch modifies three files; each change is marked with a comment in the file.

- `cel_expr_python/py_cel_function.cc`: `PyCelFunctionAdapter::Invoke` releases the argument tuple and the
  function's result (backport of upstream commit 4e64447671ae530661c946c2e4f6b863213c7b33).
- `cel_expr_python/py_cel_value.cc`: `CelValueToPyObject` returns a new reference to `None` (same upstream commit).
- `cel_expr_python/py_error_status.cc`: `PyErrorToStatus` copies an exception's message before releasing the string
  that holds it (a Dewpoint change, not upstream).

Packaging differs from upstream's 0.1.3 wheels: only the `cel_expr_python` package is included, and the licences of
the statically linked third-party libraries are in `third_party_licenses/`.

## Third-party code linked into the extension modules

cel-cpp, cel-spec, abseil-cpp (Apache-2.0); protobuf, re2, the ANTLR 4 C++ runtime, pybind11, pybind11_abseil
(BSD-3-Clause); utf8_range, yaml-cpp (MIT). Their licence texts are in `third_party_licenses/`.
