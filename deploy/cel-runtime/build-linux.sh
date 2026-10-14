#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Runs inside the pinned manylinux_2_28 image of its architecture:
#   aarch64: quay.io/pypa/manylinux_2_28_aarch64@sha256:3ab937ec86ca568d546a98e2d2616be3282e3e42b8e18ca0c233dcf9fb6293e6
#   x86_64:  quay.io/pypa/manylinux_2_28_x86_64@sha256:d3f051574f040b4c1d23b18fd06741cd7288c6f537faa0a76b1c7edf048bfa62
# /in: read-only (src/, tools/); /out: wheels, logs, lockfile; /bazel-root: Bazel's output root (a Docker volume).
set -euo pipefail
PY=/opt/python/cp312-cp312/bin/python
mkdir -p /usr/local/bazel/bin
cat > /usr/local/bazel/bin/bazel <<'W'
#!/bin/bash
export BAZELISK_HOME=/bazel-root/bazelisk-home
export USE_BAZEL_VERSION=8.5.1
case "$(uname -m)" in
  aarch64) BAZELISK=bazelisk-linux-arm64; export BAZELISK_VERIFY_SHA256=b7f2a85595e8a87d54843bc656c1e379fd9b8c1b5f783dc41717c1d7eb7cc49f ;;
  x86_64) BAZELISK=bazelisk-linux-amd64; export BAZELISK_VERIFY_SHA256=61d89402f0368e64b6c827be5de79d8e65382e8124c3cbb97325611a1851392e ;;
esac
exec /in/tools/$BAZELISK --output_user_root=/bazel-root/out "$@"
W
chmod +x /usr/local/bazel/bin/bazel
export PATH=/usr/local/bazel/bin:$PATH
"$PY" -m pip install -q setuptools==82.0.1 wheel build
"$PY" -m pip freeze > /out/build-env.freeze.txt
{ gcc --version | head -1; auditwheel --version; ldd --version | head -1; } > /out/toolchain.txt
PYTHON="$PY" /in/tools/assemble.sh /in/src /in/tools /work
cd /work
export CEL_BAZEL_FLAGS="--lockfile_mode=${LOCKFILE_MODE:-update} --repository_cache=/bazel-root/repo-cache --local_resources=memory=6000 --jobs=${JOBS:-8}"
"$PY" -m build --wheel --no-isolation --outdir /out/raw
auditwheel repair -w /out/wheelhouse /out/raw/*.whl
cp /work/MODULE.bazel.lock /out/MODULE.bazel.lock
