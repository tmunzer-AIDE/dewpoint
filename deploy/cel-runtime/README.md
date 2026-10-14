# The patched CEL runtime

Dewpoint evaluates CEL with `cel-expr-python`. Version 0.1.3, the latest on PyPI, keeps the arguments and the result
of every call CEL makes to a Python function alive for the life of the process (`PyCelFunctionAdapter::Invoke` never
releases them). Upstream fixed it in commit 4e644476, which isn't released. Until it is, Dewpoint installs
`cel-expr-python 0.1.3+dewpoint.1`: 0.1.3 with the patch in this directory, built from these files.

## What's here

- `dewpoint-cel-0.1.3-backport.patch`: three changes, described in `DEWPOINT_CHANGES.md`, which every wheel carries
  with the licences of the libraries it links (`third_party_licenses/`).
- `MODULE.bazel.lock`: the Bazel dependency graph the wheels were built with. Upstream commits none.
- `prepare.sh`, `assemble.sh`, `build-linux.sh`, `build-macos.sh`: the build.
- `manifest.json`: the build record. Every input, each wheel's sha256, and how long each build took.

## The wheels

Three, for CPython 3.12: Linux x86_64 and aarch64 (`manylinux_2_28` images, pinned by digest), and macOS arm64
(deployment target 11.0). They're on the GitHub pre-release `cel-expr-python-0.1.3-dewpoint.1`, and
`backend/uv.lock` pins each by URL and sha256: a changed file fails every install.
`backend/tests/engine/cel/test_runtime_build.py` checks that the lock and this record agree.

## Rebuilding

```bash
SRC=$(mktemp -d)/src OUT=$(mktemp -d)
deploy/cel-runtime/prepare.sh "$SRC"
# Linux, each in its pinned image (x86_64 runs under Rosetta on Apple Silicon; 4 jobs fit an 8 GB Docker VM)
docker run --rm --platform linux/arm64 -e LOCKFILE_MODE=error -v "$SRC":/in/src:ro \
  -v "$PWD/deploy/cel-runtime":/in/tools:ro -v "$OUT/linux-aarch64":/out -v cel-runtime-aarch64:/bazel-root \
  quay.io/pypa/manylinux_2_28_aarch64@sha256:3ab937ec86ca568d546a98e2d2616be3282e3e42b8e18ca0c233dcf9fb6293e6 \
  /in/tools/build-linux.sh
docker run --rm --platform linux/amd64 -e LOCKFILE_MODE=error -e JOBS=4 -v "$SRC":/in/src:ro \
  -v "$PWD/deploy/cel-runtime":/in/tools:ro -v "$OUT/linux-x86_64":/out -v cel-runtime-x86_64:/bazel-root \
  quay.io/pypa/manylinux_2_28_x86_64@sha256:d3f051574f040b4c1d23b18fd06741cd7288c6f537faa0a76b1c7edf048bfa62 \
  /in/tools/build-linux.sh
# macOS arm64, on a Mac with the Command Line Tools
deploy/cel-runtime/build-macos.sh "$SRC" "$(mktemp -d)" "$OUT/macos"
shasum -a 256 "$OUT"/*/wheelhouse/*.whl "$OUT"/macos/*.whl
```

Compare the sums with `manifest.json`. Whether a rebuild is identical byte for byte is recorded there, under
`reproducible`. Delete the two Docker volumes afterwards.

### Behind a proxy that blocks www.antlr.org

cel-cpp downloads the ANTLR tool jar from www.antlr.org, pinned by sha256. Where a proxy blocks that site, take the
same bytes from Maven Central and put them in the build's repository cache first, under the jar's hash and the marker
Bazel keys its URL by (`build-macos.sh`: `$WORK/repo-cache`; `build-linux.sh`: `/bazel-root/repo-cache`, in a
container that mounts the volume):

```bash
H=eae2dfa119a64327444672aff63e9ec35a20180dc5b8090b7a6ab85125df4d76  # the jar, as cel-cpp pins it
ID=241c9adb8906223336c1f739551c1c4740c1fad160d327e3dc33c173c5e97f7e  # sha256 of its www.antlr.org URL
mkdir -p "$CACHE/content_addressable/sha256/$H"
curl -fsSL -o "$CACHE/content_addressable/sha256/$H/file" \
  https://repo1.maven.org/maven2/org/antlr/antlr4/4.13.2/antlr4-4.13.2-complete.jar
touch "$CACHE/content_addressable/sha256/$H/id-$ID"
shasum -a 256 "$CACHE/content_addressable/sha256/$H/file"  # must print $H
```

## Changing it

Any change to the wheels is a new version (`0.1.3+dewpoint.2`), so a new CEL profile and an `ENGINE_ABI` bump
(`docs/operations/deployment.md`). When upstream releases a version with 4e644476, move to it the same way, and drop
this directory unless the release still lacks the third change.
