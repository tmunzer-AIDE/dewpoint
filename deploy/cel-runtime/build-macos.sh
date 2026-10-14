#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# The macOS arm64 wheel, built on the host. It needs the Command Line Tools: rules_cc 0.2.16's toolchain accepts only
# their SDK root, and Xcode 27's clang lists the SDK's SDKSettings.json as a dependency, which Bazel refuses under an
# Xcode.app SDK ("absolute path inclusion(s)"). DEVELOPER_DIR is set for this build only; xcode-select isn't touched.
# usage: build-macos.sh SRC_DIR WORK_DIR OUT_DIR   (SRC_DIR: prepare.sh's patched source)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$1 WORK=$2 OUT=$3
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
mkdir -p "$WORK/bin" "$OUT"
cat > "$WORK/bin/bazel" <<W
#!/bin/bash
export BAZELISK_HOME="$WORK/bazelisk-home" USE_BAZEL_VERSION=8.5.1
export BAZELISK_VERIFY_SHA256=cb6d2f19ad92157e7186f64151e665c1b0c3bacaa690784e66f446f1b7660140
exec "$HERE/bazelisk-darwin-arm64" --output_user_root="$WORK/bazel-root" "\$@"
W
chmod +x "$WORK/bin/bazel"
uv venv -q --python 3.12 "$WORK/venv"
uv pip install -q --python "$WORK/venv/bin/python" setuptools==82.0.1 wheel==0.48.0 build==1.6.1
PYTHON="$WORK/venv/bin/python" "$HERE/assemble.sh" "$SRC" "$HERE" "$WORK/tree"
cd "$WORK/tree"
PATH="$WORK/bin:$WORK/venv/bin:$PATH" MACOSX_DEPLOYMENT_TARGET=11.0 ARCHFLAGS="-arch arm64" \
  CEL_BAZEL_FLAGS="--lockfile_mode=error --repository_cache=$WORK/repo-cache --action_env=DEVELOPER_DIR --host_action_env=DEVELOPER_DIR" \
  "$WORK/venv/bin/python" -m build --wheel --no-isolation --outdir "$OUT"
