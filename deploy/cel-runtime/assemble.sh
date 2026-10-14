#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Assembles a wheel build tree from the patched source the way upstream's release scripts do (release/* to the root,
# tests removed, version set), plus Dewpoint's packaging: only cel_expr_python, licences and the change notice.
# usage: assemble.sh SRC_DIR TOOLS_DIR DEST_DIR   (DEST keeps only its bazel-* convenience links)
set -euo pipefail
SRC=$1 TOOLS=$2 DEST=$3
VERSION="0.1.3+dewpoint.1"
mkdir -p "$DEST"
find "$DEST" -mindepth 1 -maxdepth 1 ! -name 'bazel-*' -exec rm -rf {} +
(cd "$SRC" && tar --exclude=.git -cf - .) | (cd "$DEST" && tar -xf -)
find "$DEST/release" -maxdepth 1 -type f -exec cp {} "$DEST"/ \;
rm -f "$DEST"/cel_expr_python/*_test.py
"${PYTHON:-python3}" - "$DEST/pyproject.toml" "$VERSION" <<'PY'
import sys
path, version = sys.argv[1], sys.argv[2]
text = open(path).read()
for old, new in [
    ('version = "$VERSION"', f'version = "{version}"'),
    ('license = "Apache-2.0"\n',
     'license = "Apache-2.0 AND BSD-3-Clause AND MIT"\n'
     'license-files = ["LICENSE", "DEWPOINT_CHANGES.md", "dewpoint-cel-0.1.3-backport.patch", "third_party_licenses/*"]\n'),
    ('[tool.setuptools.packages.find]\nwhere = ["."]\n',
     '[tool.setuptools.packages.find]\nwhere = ["."]\ninclude = ["cel_expr_python*"]\n'),
]:
    assert text.count(old) == 1, old
    text = text.replace(old, new)
open(path, "w").write(text)
PY
cp "$TOOLS/DEWPOINT_CHANGES.md" "$TOOLS/dewpoint-cel-0.1.3-backport.patch" "$DEST"/
cp -R "$TOOLS/third_party_licenses" "$DEST/third_party_licenses"
cp "$TOOLS/MODULE.bazel.lock" "$DEST/MODULE.bazel.lock"
