#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# The patched source and the build tools, pinned: cel-python v0.1.3 plus this directory's patch, and bazelisk v1.29.0
# for each build platform, checked against GitHub's published digests (Bazel itself, 8.5.1, is pinned and checked by
# the build scripts). The bazelisk binaries land beside this script, where build-*.sh look for them (.gitignore).
# usage: prepare.sh SRC_DIR
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$1
COMMIT=3e369fe3dfd29ef2fcb3d8a63997e58f50e592ae
git clone -q --no-checkout https://github.com/cel-expr/cel-python.git "$SRC"
git -C "$SRC" -c advice.detachedHead=false checkout -q "$COMMIT"
git -C "$SRC" apply "$HERE/dewpoint-cel-0.1.3-backport.patch"
fetch() {  # name sha256
  curl -fsSL -o "$HERE/$1" "https://github.com/bazelbuild/bazelisk/releases/download/v1.29.0/$1"
  echo "$2  $HERE/$1" | shasum -a 256 -c -
  chmod +x "$HERE/$1"
}
fetch bazelisk-darwin-arm64 cee851f726789227d5561004e9904a52be45c3efb56f8b38b6993d6adbaa0409
fetch bazelisk-linux-arm64 e20e8b0f4f240091b7a55bf17b9398bd4f40ee70ae0208dff95dd4c445fb4010
fetch bazelisk-linux-amd64 5a408715e932c0250d28bd84555f12edbf70117de42f9181691c736eacc4a992
