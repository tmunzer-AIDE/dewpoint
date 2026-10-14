# CEL Runtime Backport (cel-expr-python 0.1.3+dewpoint.1, ENGINE_ABI 8 with #16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `cel-expr-python==0.1.3` with the pinned, patched `0.1.3+dewpoint.1` wheels, so a CEL call to one of
Dewpoint's Python functions no longer keeps its arguments and result alive for the life of the process, and ship the
new CEL profile in the same `ENGINE_ABI` 8 bump as #16's yield-timer fix.

**Architecture:** The wheels are built outside the repository from a recipe committed under `deploy/cel-runtime/`
(source commit, patch, Bazel lockfile, pinned images and tools, a build record), and hosted on a GitHub pre-release of
this repository. `backend/uv.lock` installs them by URL and sha256 for three platforms, and the backend declares
CPython 3.12 only. The runtime version is part of the CEL profile, so the profile becomes
`cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1`; that is an engine-ABI change, which rides ABI 8 with #16 (`51866a26`), whose
abi8 golden histories are recorded again under the new profile.

**Tech Stack:** CPython 3.12, uv ≥ 0.13, cel-expr-python 0.1.3+dewpoint.1 (Bazel 8.5.1, manylinux_2_28), the Temporal
Python SDK 1.33.0, pytest, Docker Compose.

**Spec:** the backport proposal, version 2: https://claude.ai/artifact/7tzhvaxNt77weBpmDd1Gpx (private; local copy
`~/4_dev/mist_dewpoint-2b4b-m4/cel-gate-activations/leak/proposal/cel-leak-backport.html`). It answers the CPU Gate 7b
Handoff (step 2b) and two reviews; its decisions and the owner's rulings since are in Global Constraints below. The
running record is `~/4_dev/mist_dewpoint-2b4b-m4/ledger.md` ("CEL leak" entries, 2026-10-13); the build record and
the built wheels are in `~/4_dev/cel-backport-build/` (`manifest.json`, `dist/`).

## Before you start

These hold before Task 1; none is a step of this plan.

1. **The wheels are published.** A GitHub pre-release `cel-expr-python-0.1.3-dewpoint.1` on `tmunzer-AIDE/dewpoint`
   carries the three wheels named in Global Constraints, byte-identical to `~/4_dev/cel-backport-build/dist/`. Check:
   `gh release view cel-expr-python-0.1.3-dewpoint.1 --repo tmunzer-AIDE/dewpoint --json assets --jq '.assets[].name'`
   lists the three names.
2. **The branch.** ABI 8's histories must be recorded under the new profile before abi8 reaches `main`, and the replay
   gate refuses changing a history that is already on `main`. So #16 and this plan land together, as one PR. Create
   the branch from #16's commit, and merge `origin/main` into it:

   ```bash
   cd ~/4_dev/mist_dewpoint
   git fetch origin
   git worktree add -b fix/cel-backport ~/4_dev/mist_dewpoint-celbackport 51866a26
   cd ~/4_dev/mist_dewpoint-celbackport
   git merge --no-edit origin/main
   ```

   Expected: a clean merge (main's commits since `d4ab0dbe`: #94–#97 touch only tests, #98 the egress and Mist JSON
   decoding). The session that owns
   #16 ("phase 2") agreed to the shared bump; tell it this branch carries `51866a26`, so #16 isn't pushed alone.
3. **Commits.** Each commit step runs only with the owner's explicit go in their own message (`approval-wording`).
   Ask once, before Task 1's commit, whether the go covers this plan's local commits. Pushes, the PR, CI dispatches and
   uploads each need their own go.
4. **The environment.** `backend/` needs a CPython 3.12 virtualenv. The main checkout's is 3.14 and can't install the
   new lock; this worktree gets its own: `cd backend && uv sync --locked` after Task 2's lock (until then, `uv sync`
   with the current lock). Docker must be running (tests' PostgreSQL, the recorder, Compose).

## Global Constraints

- Package version: `0.1.3+dewpoint.1`. CEL profile: `cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1` (owner: "a: keep").
- Patch: `dewpoint-cel-0.1.3-backport.patch`, sha256 `38c995fb5ae21354dfa6cb482fb4857e1872e7d7b9e7d67b44ec02748d1caf16`
  — P1 (`Invoke` releases its argument tuple and result), P2 (`Py_INCREF(Py_None)`), P3 (copy an exception's message
  before releasing it; owner: "b: include").
- Source: cel-python commit `3e369fe3dfd29ef2fcb3d8a63997e58f50e592ae` (tag v0.1.3).
- Wheels, sha256:
  - `cel_expr_python-0.1.3+dewpoint.1-cp312-cp312-macosx_11_0_arm64.whl`
    `3ef6e7f046129948a1f429eb8d78fcf6842e91071ab0ba2f635babdca9ae6733`
  - `cel_expr_python-0.1.3+dewpoint.1-cp312-cp312-manylinux_2_26_aarch64.manylinux_2_28_aarch64.whl`
    `cd32ceb4aea7c3257d1ae1640d5d104a518b2b41094763fc2a8734c85f905bc3`
  - `cel_expr_python-0.1.3+dewpoint.1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl`
    `deb256960ff194e023dff8559f15e5a82aeb6f6b609e69d024509491ef921318`
- Wheel URLs: `https://github.com/tmunzer-AIDE/dewpoint/releases/download/cel-expr-python-0.1.3-dewpoint.1/` plus the
  wheel name with `+` written `%2B`.
- `requires-python = ">=3.12,<3.13"` (the second review: "make that explicit in the project metadata").
- `[tool.uv] environments`: exactly `sys_platform == 'linux' and platform_machine == 'x86_64'`,
  `sys_platform == 'linux' and platform_machine == 'aarch64'`, `sys_platform == 'darwin' and platform_machine == 'arm64'`.
- `ENGINE_ABI = 8`, shared with `51866a26` (the owner's decision, relayed from session "phase 2"); editor 4d-1a moves
  to ABI 9 and lands after this.
- The retention tests measure 4,000 calls (owner: "1. go"); they pass unchanged otherwise.
- From the handoff, never: change `TASK_CPU_TARGET_S` or the gate's assertion; disable, pause or subtract garbage
  collection; release leaked references from Python (`ctypes`, `Py_DecRef`); route CEL calls elsewhere to avoid the
  leak.
- Migration `0007_workflows.py` keeps its seed `cel-cpp-0.1.3/fn-1/cls-1`: it records what existing versions were
  published under. `dewpoint plugins sync` registers the new profile.

## Review Focus

1. **An evaluator image installs the wheel of its own architecture.** The export lists three `cel-expr-python @ <url>
   ; <marker>` entries; the image must install exactly the one whose marker matches (amd64 in CI and production, arm64
   on Apple Silicon), or fail the build. Task 2's Step 9 builds the image for linux/arm64 and reads the installed
   version; CI's `e2e` job builds it for amd64.
2. **Temporal accepts a `+` in a task queue name.** The evaluator queue becomes
   `dewpoint-cel.abi8.cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1`. Task 4's recording runs the evaluator scenario through it,
   and Task 4's Step 4 checks the recorded history names it; Task 5's Compose proof runs it against a real server.
3. **A developer on CPython 3.13 or 3.14.** `uv sync` must refuse at once with the project's Python requirement, not
   fail later on a wheel tag. Task 2's Step 10 runs it.
4. **A callback's exception message under a debug allocator (P3).** A `KeyError`, a multi-argument exception or a
   non-string argument must come back as its exact message. Task 2's `test_runtime_conversions.py` runs this in a
   `python -X dev` child, where freed memory is overwritten.
5. **The lock drifting from the recorded build.** A re-lock or a hand edit could pin other bytes than the ones the
   build recorded. Task 2's `test_the_lock_installs_the_recorded_wheels` compares the lock's three hashes with the
   build record.

## File Structure

- `deploy/cel-runtime/` (new): the recipe and the build record. `README.md` (what, why, rebuild, verify, update),
  `prepare.sh` (patched source and tools), `assemble.sh` (the wheel build tree), `build-linux.sh` (in the manylinux
  image), `build-macos.sh` (on the host), the patch, `DEWPOINT_CHANGES.md`, `third_party_licenses/`,
  `MODULE.bazel.lock`, `manifest.json`, `.gitignore`.
- `backend/tests/engine/cel/test_runtime_build.py` (new): the build record matches the committed inputs; the lock
  matches the build record.
- `backend/tests/engine/cel/test_runtime_retention.py` (new): the leak's five tests.
- `backend/tests/engine/cel/test_runtime_conversions.py` (new): null paths, callback errors, conversions, lifetime.
- `backend/pyproject.toml`, `backend/uv.lock`: the pin, the sources, the Python bound, the environments.
- `deploy/docker/cel-evaluator.Dockerfile`: the export filter accepts URL entries.
- `backend/src/dewpoint/engine/cel/profile.py`: `RUNTIME_VERSION`.
- `backend/tests/engine/cel/test_profile.py`, `backend/tests/apps/cel_evaluator/test_limits.py`,
  `backend/tests/support/workflows.py`: the profiles that must be the current one.
- `docs/operations/deployment.md`, `docs/operations/cel-evaluator.md`, `CONTRIBUTING.md`: the new runtime.
- `backend/tests/engine/replay/dewpoint-0.1.0+abi8/`: recorded again.

Left as they are, on purpose: `test_route.py`, `test_ipc.py`, `test_server.py` and `tests/probes/migration_locks.py`
use `cel-cpp-0.1.3/fn-1/cls-1` as an arbitrary profile string that no installed runtime has to serve;
`test_gate_semantics.py` and `caps.py` describe 0.1.3's behaviour, which the patch doesn't change.

---

### Task 1: The build recipe and its record

**Files:**
- Create: `deploy/cel-runtime/README.md`, `deploy/cel-runtime/prepare.sh`, `deploy/cel-runtime/build-macos.sh`,
  `deploy/cel-runtime/.gitignore`
- Copy from `~/4_dev/cel-backport-build/tools/`: `dewpoint-cel-0.1.3-backport.patch`, `DEWPOINT_CHANGES.md`,
  `MODULE.bazel.lock`, `third_party_licenses/` (10 files), `assemble.sh`, `build-linux.sh`
- Copy from `~/4_dev/cel-backport-build/`: `manifest.json` (then update two entries)
- Test: `backend/tests/engine/cel/test_runtime_build.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `deploy/cel-runtime/manifest.json` with keys `version`, `source`, `patch` (`file`, `sha256`), `assembly`
  (`script`, `sha256`), `build_linux_script` (`file`, `sha256`), `MODULE.bazel.lock` (`sha256`),
  `third_party_licenses` ({name: sha256}), `wheels` ({wheel name: {`sha256`, `bytes`}}); the test module's
  `RECIPE: Path`, `sha256(path) -> str`, `manifest() -> dict`, which Task 2 extends.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/engine/cel/test_runtime_build.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The patched CEL runtime's build record (deploy/cel-runtime/manifest.json) names the inputs committed beside it.
Nothing here builds: deploy/cel-runtime/README.md says how."""

import hashlib
import json
from pathlib import Path
from typing import Any

RECIPE = Path(__file__).parents[4] / "deploy" / "cel-runtime"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> dict[str, Any]:
    return json.loads((RECIPE / "manifest.json").read_text())


def test_the_build_record_names_the_committed_inputs() -> None:
    record = manifest()
    assert record["patch"]["sha256"] == sha256(RECIPE / record["patch"]["file"])
    assert record["MODULE.bazel.lock"]["sha256"] == sha256(RECIPE / "MODULE.bazel.lock")
    assert record["assembly"]["sha256"] == sha256(RECIPE / "assemble.sh")
    assert record["build_linux_script"]["sha256"] == sha256(RECIPE / "build-linux.sh")
    assert {p.name: sha256(p) for p in (RECIPE / "third_party_licenses").iterdir()} == record["third_party_licenses"]
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd backend && uv run pytest -q tests/engine/cel/test_runtime_build.py`
Expected: FAIL with `FileNotFoundError` on `deploy/cel-runtime/manifest.json`.

- [ ] **Step 3: Copy the recorded inputs**

```bash
cd ~/4_dev/mist_dewpoint-celbackport
B=~/4_dev/cel-backport-build
mkdir -p deploy/cel-runtime
cp "$B/tools/dewpoint-cel-0.1.3-backport.patch" "$B/tools/DEWPOINT_CHANGES.md" "$B/tools/MODULE.bazel.lock" \
   "$B/tools/assemble.sh" "$B/tools/build-linux.sh" "$B/manifest.json" deploy/cel-runtime/
cp -R "$B/tools/third_party_licenses" deploy/cel-runtime/
shasum -a 256 deploy/cel-runtime/dewpoint-cel-0.1.3-backport.patch deploy/cel-runtime/MODULE.bazel.lock
```

Expected: `38c995fb5ae21354dfa6cb482fb4857e1872e7d7b9e7d67b44ec02748d1caf16` for the patch and
`6a10850eb49d1517da8e1bc1d58dd38bbfe2213c08d23a49911b237d1fe46d8f` for the lockfile.

- [ ] **Step 4: Give the two scripts their SPDX line**

Both start with `#!/bin/bash`; insert the header as line 2 (CONTRIBUTING: every source file starts with it):

```bash
cd ~/4_dev/mist_dewpoint-celbackport/deploy/cel-runtime
for f in assemble.sh build-linux.sh; do
  { head -1 "$f"; echo '# SPDX-License-Identifier: Apache-2.0'; tail -n +2 "$f"; } > "$f.new" && mv "$f.new" "$f"
  chmod +x "$f"
done
head -3 assemble.sh build-linux.sh
```

Expected: each shows `#!/bin/bash`, then `# SPDX-License-Identifier: Apache-2.0`, then its first comment line.

- [ ] **Step 5: Write `prepare.sh`**

```bash
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
```

- [ ] **Step 6: Write `build-macos.sh`**

It encodes the commands that built the recorded macOS wheel (ledger, 2026-10-13), with the lockfile enforced:

```bash
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
```

- [ ] **Step 7: Write `.gitignore`**

```
# prepare.sh's downloads
bazelisk-*
```

- [ ] **Step 8: Write `README.md`**

````markdown
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

## Changing it

Any change to the wheels is a new version (`0.1.3+dewpoint.2`), so a new CEL profile and an `ENGINE_ABI` bump
(`docs/operations/deployment.md`). When upstream releases a version with 4e644476, move to it the same way, and drop
this directory unless the release still lacks the third change.
````

- [ ] **Step 9: Point the build record at the committed scripts**

The SPDX lines changed the two scripts after the build, by a comment only. Record the committed files, and say so:

```bash
cd ~/4_dev/mist_dewpoint-celbackport
python3 - <<'EOF'
import hashlib, json, pathlib
r = pathlib.Path("deploy/cel-runtime")
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
m = json.loads((r / "manifest.json").read_text())
note = "the build ran this script without its SPDX comment line, added when it was committed"
m["assembly"] = {"script": "deploy/cel-runtime/assemble.sh", "sha256": sha(r / "assemble.sh"), "note": note}
m["build_linux_script"] = {"file": "deploy/cel-runtime/build-linux.sh", "sha256": sha(r / "build-linux.sh"), "note": note}
m["patch"]["file"] = "dewpoint-cel-0.1.3-backport.patch"
(r / "manifest.json").write_text(json.dumps(m, indent=1) + "\n")
EOF
```

- [ ] **Step 10: Run the test to see it pass**

Run: `cd backend && uv run pytest -q tests/engine/cel/test_runtime_build.py`
Expected: `1 passed`.

- [ ] **Step 11: Check the recipe rebuilds the macOS wheel**

About 5 minutes on an Apple Silicon Mac, from cold:

```bash
cd ~/4_dev/mist_dewpoint-celbackport
T=$(mktemp -d ~/cel-rebuild-XXXX)
deploy/cel-runtime/prepare.sh "$T/src" && deploy/cel-runtime/build-macos.sh "$T/src" "$T/work" "$T/out"
shasum -a 256 "$T"/out/*.whl
```

Expected: the wheel builds. Record the outcome in `manifest.json` under `reproducible.macos-arm64`, with the date:
"rebuilt identical" if its sha256 equals the manifest's macOS entry; otherwise "rebuilt, differs" and which files
differ (`unzip -l` of both wheels, and `cmp` of the `.so` files). Either is a result, not a failure; rerun Step 10
after editing the manifest. Then delete `$T` and the downloaded `deploy/cel-runtime/bazelisk-*`.

- [ ] **Step 12: Commit** (the owner's go, Before you start 3)

```bash
git add deploy/cel-runtime backend/tests/engine/cel/test_runtime_build.py
git commit -s -m "build(cel): the patched cel-expr-python 0.1.3+dewpoint.1's recipe and build record"
```

---

### Task 2: Install the patched runtime, and its profile

**Files:**
- Create: `backend/tests/engine/cel/test_runtime_retention.py`, `backend/tests/engine/cel/test_runtime_conversions.py`
- Modify: `backend/tests/engine/cel/test_runtime_build.py` (one test added)
- Modify: `backend/pyproject.toml:6` (`requires-python`), `:23` (the pin); add `[tool.uv]` and `[tool.uv.sources]`
- Modify: `backend/uv.lock` (re-locked)
- Modify: `deploy/docker/cel-evaluator.Dockerfile:10-13`
- Modify: `backend/src/dewpoint/engine/cel/profile.py:6`
- Modify: `backend/tests/engine/cel/test_profile.py:10`, `backend/tests/apps/cel_evaluator/test_limits.py:22`,
  `backend/tests/support/workflows.py:10`

**Interfaces:**
- Consumes: Task 1's `RECIPE`, `sha256`, `manifest()` and `manifest.json`'s `wheels` and `version`.
- Produces: `profile.RUNTIME_VERSION == "0.1.3+dewpoint.1"`, so `profile.CURRENT_CEL_PROFILE ==
  "cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1"`; Task 4 records histories under it.

- [ ] **Step 1: Write the leak's tests**

Create `backend/tests/engine/cel/test_runtime_retention.py` (the five tests the handoff wrote, with the owner's 4,000
calls and the current profile):

```python
# SPDX-License-Identifier: Apache-2.0
"""An evaluation keeps nothing it passed to, or got back from, one of our functions (fn-1).

cel-expr-python 0.1.3 never releases the argument tuple it builds for a call to a Python function, nor the value the
function returns (its `PyCelFunctionAdapter::Invoke`); the cel-gates process held 1,200 copies of one load's map
argument, 241,000 lists that every later full collection walked. The patched runtime (deploy/cel-runtime) releases
both. Counted in objects and bytes, never timed."""

import gc
import tracemalloc
from collections.abc import Callable
from typing import Any

from dewpoint.engine.cel import evaluate, ipc, profile, runtime
from dewpoint.engine.cel import types as T

KEPT = "0-kept"  # a key and an item only these tests' values hold; it sorts first
TIMES = 20


def kept(found: Callable[[Any], bool]) -> int:
    """Objects the collector tracks that match `found`, after a full collection."""
    gc.collect()
    return sum(1 for o in gc.get_objects() if found(o))


def added(found: Callable[[Any], bool], run: Callable[[], None]) -> int:
    """How many more objects match `found` once `run` is done: what it kept, whatever ran before it."""
    before = kept(found)
    run()
    return kept(found) - before


def map_copies(original: dict[str, Any]) -> Callable[[Any], bool]:
    return lambda o: type(o) is dict and KEPT in o and o is not original


def key_lists(o: Any) -> bool:
    return type(o) is list and len(o) == 2 and o[0] == KEPT


def test_a_maps_copies_and_the_keys_returned_are_not_kept() -> None:
    m = {KEPT: [1, 2, 3], "b": [4, 5]}
    program = runtime.compile_checked("size(sortedKeys(m)) == 2", {"m": T.MAP})

    def run() -> None:
        for _ in range(TIMES):
            assert runtime.evaluate(program, {"m": m}) == runtime.RawResult("value", True, "BOOL")

    assert added(lambda o: map_copies(m)(o) or key_lists(o), run) == 0


def test_a_list_returned_as_it_came_is_not_kept() -> None:
    items = [KEPT, "b", "c"]
    program = runtime.compile_checked("size(asList(l)) == 3", {"l": T.LIST})

    def run() -> None:
        for _ in range(TIMES):
            assert runtime.evaluate(program, {"l": items}).value is True

    assert added(lambda o: type(o) is list and o[:1] == [KEPT] and o is not items, run) == 0


# Any traced window shows a few KB that don't grow with the calls (blocks allocated before tracing starts, reallocated
# inside it): 400 calls put that over 8 B a call on Linux; 4000 put it near 1 B, against about 156 B a call leaked.
def bytes_kept_per_evaluation(expr: str, values: dict[str, Any], times: int = 4000) -> float:
    program = runtime.compile_checked(expr, dict.fromkeys(values, T.STRING))
    for _ in range(20):  # caches warm first
        runtime.evaluate(program, values)
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        for _ in range(times):
            runtime.evaluate(program, values)
        gc.collect()
        return (tracemalloc.get_traced_memory()[0] - before) / times
    finally:
        tracemalloc.stop()


def test_calls_with_strings_and_failing_calls_keep_nothing() -> None:
    assert bytes_kept_per_evaluation('ipInCidr(s, "10.0.0.0/8")', {"s": "10.1.2.3"}) < 8
    assert bytes_kept_per_evaluation("macNormalize(s)", {"s": "00:1A:2B:3C:4D:5E"}) < 8
    assert bytes_kept_per_evaluation("macOui(s)", {"s": "not a mac address"}) < 8  # a CEL error value


def test_the_interpreters_local_evaluations_keep_nothing() -> None:
    m = {KEPT: [1], "b": [2]}
    program = evaluate.compiled("sortedKeys(m)", {"m": T.MAP})

    def run() -> None:
        for _ in range(TIMES):
            assert evaluate.run(program, {"m": m}) == evaluate.Outcome(value=[KEPT, "b"])

    assert added(lambda o: map_copies(m)(o) or key_lists(o), run) == 0


def test_the_evaluators_requests_keep_nothing() -> None:
    """The evaluator child's work for one request (its process exits after each; within one, nothing piles up)."""
    m = {KEPT: [1], "b": [2]}
    request = ipc.EvaluateRequest(
        profile.CURRENT_CEL_PROFILE, "sortedKeys(m)", {"m": T.MAP}, tuple({"m": m} for _ in range(TIMES))
    )
    expected = ipc.results_response([evaluate.Outcome(value=[KEPT, "b"])] * TIMES)

    def run() -> None:
        assert ipc.evaluate_request(request) == expected

    assert added(lambda o: map_copies(m)(o) or key_lists(o), run) == 0
```

- [ ] **Step 2: Write the conversion tests**

Create `backend/tests/engine/cel/test_runtime_conversions.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What the patched runtime (deploy/cel-runtime) changed beside the leak, and what it must not change: null values
through the paths whose ownership it fixed, a callback's exception message, conversions that fail, and values our
functions return, used after the call. The library is used directly where our functions can't reach a path."""

import gc
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from cel_expr_python import cel

from dewpoint.engine.cel import functions, runtime
from dewpoint.engine.cel import types as T

S = cel.Type.STRING
TIMES = 2000


def library_expr(
    expr: str, impl: Callable[..., Any], params: list[Any], variables: dict[str, Any] | None = None
) -> Any:
    decl = cel.FunctionDecl("f", [cel.Overload("f_o", S, params, impl=impl)])
    return cel.NewEnv(variables=variables or {}, functions=[decl]).compile(expr)


def test_a_null_argument_reaches_the_function_as_none() -> None:
    seen: list[Any] = []
    expr = library_expr("f(null)", lambda x: seen.append(x) or "ok", [cel.Type.NULL])  # a dyn overload isn't matched
    for _ in range(TIMES):
        assert expr.eval().plain_value() == "ok"
    assert seen == [None] * TIMES


def test_null_map_values_and_list_elements_reach_our_functions() -> None:
    program = runtime.compile_checked("sortedKeys(m) == ['a', 'b'] && size(asList(l)) == 3", {"m": T.MAP, "l": T.LIST})
    for _ in range(TIMES):
        assert runtime.evaluate(program, {"m": {"a": None, "b": 1}, "l": [None, 1, None]}) == runtime.RawResult(
            "value", True, "BOOL"
        )


def test_null_elements_come_back_from_our_functions() -> None:
    program = runtime.compile_checked("asList(l)", {"l": T.LIST})
    for _ in range(TIMES):
        assert runtime.evaluate(program, {"l": [None, "x", None]}).value == [None, "x", None]


# A child under the debug allocator (-X dev), which overwrites freed memory: 0.1.3 read the message after releasing
# the string that held it, which a plain run hides. One line per evaluation.
CALLBACK_ERRORS = """
from cel_expr_python import cel
S = cel.Type.STRING
for make in (lambda: ValueError("plain message"), lambda: KeyError("abc-key"), lambda: ValueError("two", 3),
             lambda: ValueError(12345)):
    def boom(_, make=make):
        raise make()
    decl = cel.FunctionDecl("f", [cel.Overload("f_o", S, [S], impl=boom)])
    expr = cel.NewEnv(variables={"m": S}, functions=[decl]).compile("f(m)")
    for _ in range(50):
        value = expr.eval(data={"m": "x"})
        try:
            print(value.plain_value())
        except Exception as e:
            print("unconvertible:", type(e).__name__)
"""


def test_a_callbacks_exception_keeps_its_exact_message() -> None:
    done = subprocess.run(
        [sys.executable, "-X", "dev", "-c", CALLBACK_ERRORS], capture_output=True, text=True, check=True, timeout=120
    )
    assert set(done.stdout.splitlines()) == {
        "OUT_OF_RANGE: plain message",
        "UNKNOWN: 'abc-key'",
        "OUT_OF_RANGE: ('two', 3)",
        "OUT_OF_RANGE: 12345",
    }


def test_our_functions_errors_keep_their_message() -> None:
    program = runtime.compile_checked("macOui(s)", {"s": T.STRING})
    for _ in range(200):
        assert runtime.evaluate(program, {"s": "not a mac address"}) == runtime.RawResult(
            "error", message="OUT_OF_RANGE: invalid_argument: macNormalize: not a MAC address"
        )  # macOui reports through macNormalize, which it calls


def test_no_matching_overload_does_not_call_the_function() -> None:
    calls: list[Any] = []
    expr = library_expr("f(m)", lambda x: calls.append(x) or "ok", [S], {"m": cel.Type.DYN})
    for _ in range(200):
        assert expr.eval(data={"m": 1}).type().name() == "ERROR"
    assert calls == []


def test_an_error_argument_does_not_call_the_function() -> None:
    calls: list[Any] = []
    expr = library_expr("f(string(1 / n))", lambda x: calls.append(x) or "ok", [S], {"n": cel.Type.INT})
    for _ in range(200):
        assert expr.eval(data={"n": 0}).type().name() == "ERROR"
    assert calls == []


def test_a_wrong_result_type_is_an_error() -> None:
    value = library_expr("f(m)", lambda _: 12345, [S], {"m": S}).eval(data={"m": "x"})
    assert value.type().name() == "ERROR"
    assert "Unexpected value type" in value.plain_value()


def test_returned_values_stay_valid_after_the_call() -> None:
    program = runtime.compile_checked(
        "sortedKeys(m)[0] + '/' + macNormalize(s) + '/' + string(size(asList(l)))",
        {"m": T.MAP, "s": T.STRING, "l": T.LIST},
    )
    expected = f"aa/{functions.mac_normalize('00-1A-2B-3C-4D-5E')}/2"
    for i in range(TIMES):
        result = runtime.evaluate(program, {"m": {"zz": 1, "aa": 2}, "s": "00-1A-2B-3C-4D-5E", "l": ["x", "y"]})
        if i % 100 == 0:
            gc.collect()
        assert result.value == expected
```

- [ ] **Step 3: Add the lock's test**

Append to `backend/tests/engine/cel/test_runtime_build.py`, and add `import tomllib` and
`from dewpoint.engine.cel import profile` to its imports:

```python
def test_the_lock_installs_the_recorded_wheels() -> None:
    lock = tomllib.loads((RECIPE.parents[1] / "backend" / "uv.lock").read_text())
    entries = [p for p in lock["package"] if p["name"] == "cel-expr-python"]
    locked = {w["url"].rsplit("/", 1)[1].replace("%2B", "+"): w["hash"] for e in entries for w in e.get("wheels", [])}
    record = manifest()
    assert locked == {name: f"sha256:{w['sha256']}" for name, w in record["wheels"].items()}
    assert {e["version"] for e in entries} == {record["version"]} == {profile.RUNTIME_VERSION}
```

- [ ] **Step 4: Run them against 0.1.3 to see them fail**

Run: `cd backend && uv run pytest -q tests/engine/cel/test_runtime_retention.py tests/engine/cel/test_runtime_conversions.py tests/engine/cel/test_runtime_build.py`
Expected: 7 failed. The five retention tests (about 157 bytes per call kept); `test_a_callbacks_exception_keeps_its_exact_message`
(three lines are `unconvertible: TypeError`); `test_the_lock_installs_the_recorded_wheels` (0.1.3's PyPI wheels).
The other conversion tests and Task 1's test pass.

- [ ] **Step 5: Point the backend at the patched wheels**

In `backend/pyproject.toml`, change line 6 to `requires-python = ">=3.12,<3.13"`, and line 23 to
`  "cel-expr-python==0.1.3+dewpoint.1",`. Then add, before `[tool.hatch.build.targets.wheel]`:

```toml
# CPython 3.12 on three platforms only: the patched CEL runtime (deploy/cel-runtime) ships cp312 wheels for these, and
# nothing else. uv 0.13 locks per-platform URL sources this way, and writes the lock's format.
[tool.uv]
required-version = ">=0.13"
environments = [
  "sys_platform == 'linux' and platform_machine == 'x86_64'",
  "sys_platform == 'linux' and platform_machine == 'aarch64'",
  "sys_platform == 'darwin' and platform_machine == 'arm64'",
]

[tool.uv.sources]
cel-expr-python = [
  { url = "https://github.com/tmunzer-AIDE/dewpoint/releases/download/cel-expr-python-0.1.3-dewpoint.1/cel_expr_python-0.1.3%2Bdewpoint.1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl", marker = "sys_platform == 'linux' and platform_machine == 'x86_64'" },
  { url = "https://github.com/tmunzer-AIDE/dewpoint/releases/download/cel-expr-python-0.1.3-dewpoint.1/cel_expr_python-0.1.3%2Bdewpoint.1-cp312-cp312-manylinux_2_26_aarch64.manylinux_2_28_aarch64.whl", marker = "sys_platform == 'linux' and platform_machine == 'aarch64'" },
  { url = "https://github.com/tmunzer-AIDE/dewpoint/releases/download/cel-expr-python-0.1.3-dewpoint.1/cel_expr_python-0.1.3%2Bdewpoint.1-cp312-cp312-macosx_11_0_arm64.whl", marker = "sys_platform == 'darwin' and platform_machine == 'arm64'" },
]
```

- [ ] **Step 6: Re-lock, and check nothing else moved**

Compare what a CPython 3.12 environment installs before and after (the old lock also covers 3.13 and 3.14, so its
export lists versions no 3.12 environment gets):

```bash
cd backend
uv pip freeze --python .venv/bin/python | grep -v -E '^(cel-expr-python|-e |dewpoint)' > /tmp/deps-before.txt
uv lock
uv sync --locked
uv pip freeze --python .venv/bin/python | grep -v -E '^(cel-expr-python|-e |dewpoint)' > /tmp/deps-after.txt
diff /tmp/deps-before.txt /tmp/deps-after.txt && echo "no other dependency changed"
grep -n -A3 'name = "cel-expr-python"' uv.lock | head -20
```

Expected: `no other dependency changed`; three `cel-expr-python` entries, version `0.1.3+dewpoint.1`, each `source = {
url = "https://github.com/tmunzer-AIDE/dewpoint/releases/download/..." }`. If `diff` shows a version change, the
narrower Python range let uv pick another version: pin it back with `uv lock --upgrade-package <name>==<old>` and run
the step again.

- [ ] **Step 7: Name the new runtime in the profile, and in the tests that need the current one**

In `backend/src/dewpoint/engine/cel/profile.py`, line 6: `RUNTIME_VERSION = "0.1.3+dewpoint.1"`.

In `backend/tests/engine/cel/test_profile.py`, replace line 10 with:

```python
    assert profile.CURRENT_CEL_PROFILE == profile.profile_of(profile.RUNTIME_VERSION)
    assert profile.CURRENT_CEL_PROFILE == "cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1"
```

In `backend/tests/apps/cel_evaluator/test_limits.py`, add `from dewpoint.engine.cel import profile` after the line
`from dewpoint.engine.cel import ipc`, and change line 22 to:

```python
P = profile.CURRENT_CEL_PROFILE  # the profile the evaluator names from the installed runtime
```

In `backend/tests/support/workflows.py`, add a blank line and `from dewpoint.engine.cel.profile import
CURRENT_CEL_PROFILE` after `from sqlalchemy import text` (first-party imports form their own group), and change line 10
to:

```python
PROFILE = CURRENT_CEL_PROFILE  # routed like a published version (route.py compares it with LOCAL_CEL_PROFILE)
```

- [ ] **Step 8: Let the evaluator image take URL entries**

In `deploy/docker/cel-evaluator.Dockerfile`, replace lines 10–13:

```dockerfile
# The locked requirements, with their hashes: protobuf's `name==version \` line plus hash lines, and the patched CEL
# runtime's `name @ url ; marker \` line per platform (deploy/cel-runtime), of which pip installs the one that matches.
RUN uv export --locked --no-dev --no-emit-project --no-header --no-annotate > all.txt \
 && awk '/^(cel-expr-python @ |protobuf==)/{keep=1} keep{print} keep && !/\\$/{keep=0}' all.txt > requirements.txt \
 && test "$(grep -c '^cel-expr-python @ ' requirements.txt)" = 3 \
 && test "$(grep -c '^protobuf==' requirements.txt)" = 1 \
```

The two lines after it (`uv venv`, `uv pip install … --require-hashes --no-deps`) stay.

- [ ] **Step 9: Build the evaluator image, and read what it installed**

```bash
cd ~/4_dev/mist_dewpoint-celbackport
docker build --platform linux/arm64 -f deploy/docker/cel-evaluator.Dockerfile -t cel-evaluator:backport .
docker run --rm --entrypoint /app/.venv/bin/python cel-evaluator:backport -c \
  'import importlib.metadata as m, platform; print(m.version("cel-expr-python"), platform.machine())'
```

Expected: `0.1.3+dewpoint.1 aarch64`. (Review Focus 1; CI's `e2e` builds the amd64 image.)

- [ ] **Step 10: Sync, and check another Python is refused**

```bash
cd backend && uv sync --locked && uv run python -c 'import importlib.metadata as m; print(m.version("cel-expr-python"))'
UV_PROJECT_ENVIRONMENT=/tmp/venv314 uv sync --locked --python 3.14; echo "exit=$?"
```

Expected: `0.1.3+dewpoint.1`; then an error naming the project's Python requirement `==3.12.*` and `exit=2`
(Review Focus 3). If no 3.14 interpreter is on the machine, uv says so instead: note it, and skip.

- [ ] **Step 11: Run the new tests, and the CEL tests, to see them pass**

Run: `cd backend && uv run pytest -q tests/engine/cel tests/apps/cel_evaluator`
Expected: all pass, the 7 from Step 4 included.

- [ ] **Step 12: Run the whole backend suite**

Run: `cd backend && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest -q -n auto --ignore=tests/apps/cel_evaluator && uv run pytest -q tests/apps/cel_evaluator`
Expected: all pass except `tests/engine/replay/test_replay.py`, which can fail: the abi8 histories name the old
profile until Task 4. Any other failure is this task's to fix. A foreign-key error on `workflow_versions.cel_profile`
means a test seeds a version under a profile it didn't register: register the current one in that test (the way
`tests/support/workflows.py` does), never in a migration.

- [ ] **Step 13: Commit** (the owner's go)

```bash
git add backend/pyproject.toml backend/uv.lock backend/src/dewpoint/engine/cel/profile.py \
  backend/tests/engine/cel/test_runtime_retention.py backend/tests/engine/cel/test_runtime_conversions.py \
  backend/tests/engine/cel/test_runtime_build.py backend/tests/engine/cel/test_profile.py \
  backend/tests/apps/cel_evaluator/test_limits.py backend/tests/support/workflows.py \
  deploy/docker/cel-evaluator.Dockerfile
git commit -s -m "fix(cel): install cel-expr-python 0.1.3+dewpoint.1, which releases what each call to our functions passed and got back (profile cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1)"
```

---

### Task 3: The operator's documents

**Files:**
- Modify: `docs/operations/deployment.md:254-257` and the ABI 8 list
- Modify: `docs/operations/cel-evaluator.md:55-57`
- Modify: `CONTRIBUTING.md:6`

**Interfaces:**
- Consumes: Task 2's profile `cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1`.
- Produces: nothing code reads.

- [ ] **Step 1: The deployment guide's ABI 8**

Replace the paragraph at lines 254–257 with:

```markdown
ABI 8 (#16's extra workflow-task failure, and the CEL runtime's leak) changes how an execution closes and which
runtime evaluates CEL, not what publishing accepts: a workflow published under ABI 7 publishes again unchanged, as
every workflow must once the ABI 8 build is current (above). Its CEL queue is
`dewpoint-cel.abi8.cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1`: deploy the new build's evaluator workers with it, while the
old build's runs keep `dewpoint-cel.abi7.cel-cpp-0.1.3/fn-1/cls-1` until they end. What a run does differently:
```

and add this item at the end of the list that follows it:

```markdown
- CEL runs on `cel-expr-python 0.1.3+dewpoint.1` (`deploy/cel-runtime/README.md`), so the CEL profile is
  `cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1`. 0.1.3 kept the arguments and the result of every call to one of Dewpoint's
  CEL functions for the life of the process: a worker's memory, and the work of each full garbage collection, grew
  with every such call. `dewpoint plugins sync` registers the new profile (step 1 of a rollout). Keep the old
  profile's evaluators until no run of the old build is left, then retire it:
  `dewpoint lifecycle retire --cel-profile cel-cpp-0.1.3/fn-1/cls-1`.
```

- [ ] **Step 2: The evaluator's profiles**

After the paragraph under `## Profiles` in `docs/operations/cel-evaluator.md`, add:

```markdown
A profile names its runtime build. The current one, `cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1`, runs a patched
`cel-expr-python` 0.1.3, built from `deploy/cel-runtime/`.
```

- [ ] **Step 3: The contributor's setup**

In `CONTRIBUTING.md`, insert before the `- Backend:` item:

```markdown
- The backend runs on CPython 3.12 only, with uv 0.13 or newer: its CEL runtime is a patched build with wheels for
  Linux x86_64 and aarch64 and macOS arm64 (`deploy/cel-runtime/README.md`).
```

- [ ] **Step 4: Check the names**

Run: `git grep -n 'cel-cpp-0.1.3/fn-1/cls-1' -- docs/operations CONTRIBUTING.md`
Expected: only the two old-profile mentions written above (the abi7 queue and the retire command).

- [ ] **Step 5: Commit** (the owner's go)

```bash
git add docs/operations/deployment.md docs/operations/cel-evaluator.md CONTRIBUTING.md
git commit -s -m "docs: ABI 8 also moves CEL to the patched runtime; how to roll out and retire the old profile"
```

---

### Task 4: ABI 8's golden histories, recorded again

**Files:**
- Replace: `backend/tests/engine/replay/dewpoint-0.1.0+abi8/*.json` (recorded by `51866a26` under the old profile)

**Interfaces:**
- Consumes: Task 2's profile; `51866a26`'s ENGINE_ABI 8 and scenarios.
- Produces: the abi8 histories the replay gate and `test_replay.py` read.

- [ ] **Step 1: See the old profile in the abi8 histories**

Run: `git grep -c 'cel-cpp-0.1.3/fn-1/cls-1' -- backend/tests/engine/replay/dewpoint-0.1.0+abi8 | head`
Expected: three files with counts. `uv run pytest -q tests/engine/replay` may fail on them now.

- [ ] **Step 2: Remove them, and record again**

The directory isn't on `main` yet, so the gate sees only additions (`gate.py` compares with main's merge base).

```bash
cd backend
git rm -q -r tests/engine/replay/dewpoint-0.1.0+abi8
uv run python -m tests.engine.replay.record
ls tests/engine/replay/dewpoint-0.1.0+abi8 | wc -l
```

Expected: the recorder runs every scenario; the directory has the same number of files `51866a26` added (42).

- [ ] **Step 3: Replay them, and run the gate**

Run: `cd backend && uv run pytest -q tests/engine/replay && uv run python -m tests.engine.replay.gate origin/main`
Expected: all pass; the gate prints no problem.

- [ ] **Step 4: Check the new profile is in them, and the old one isn't**

```bash
git grep -c 'dewpoint-cel.abi8.cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1' -- backend/tests/engine/replay/dewpoint-0.1.0+abi8
git grep -c 'cel-cpp-0.1.3/fn-1/cls-1' -- backend/tests/engine/replay/dewpoint-0.1.0+abi8; echo "old: exit=$?"
```

Expected: at least one file names the new queue (Review Focus 2: Temporal accepted it); `old: exit=1`.

- [ ] **Step 5: Commit** (the owner's go)

```bash
git add -A backend/tests/engine/replay/dewpoint-0.1.0+abi8
git commit -s -m "test(replay): ABI 8's golden histories, recorded under cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1"
```

---

### Task 5: The whole branch, as CI and a deployment will run it

**Files:** none changed, unless a step finds a defect (then the owning task's files, test first).

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: the evidence the PR description cites.

- [ ] **Step 1: The CEL gates, as CI runs them**

```bash
cd backend
DEWPOINT_CEL_GATE_RESULTS=/tmp/cel-gate-results uv run pytest -q \
  tests/apps/cel_evaluator tests/engine/cel tests/engine/graph/test_validate_cel.py tests/apps/worker/test_gate_task_cost.py
python3 -c 'import json; L=json.load(open("/tmp/cel-gate-results/task_cost.json"))["loads"]; print(sorted(((v["worst_cpu_s"], k) for k, v in L.items()), reverse=True)[:3])'
```

Expected: all pass. The worst activations print; the local run before this plan gave 0.304 s for
`shared past the caps x30000` on macOS (x86 is the gate's platform: After this plan, item 2).

- [ ] **Step 2: The heap census at gate 7b's load**

```bash
C=~/4_dev/mist_dewpoint-2b4b-m4/cel-gate-activations/leak/census
cd backend
CENSUS_OUT=/tmp/gate.json DEWPOINT_CEL_GATE_RESULTS=/tmp/cel-gate-results PYTHONPATH=$C uv run pytest -q -p gate_census \
  tests/apps/cel_evaluator tests/engine/cel tests/engine/graph/test_validate_cel.py tests/apps/worker/test_gate_task_cost.py
python3 $C/compare.py /tmp/gate.json $C/proxy.json | head -8
```

Expected: `census taken`; retained objects near 295,000 (0.1.3: about 564,000), lists near 29,000.

- [ ] **Step 3: Upstream's own tests, on the patched source**

The patch must not break what upstream tests. Run their suite twice, on v0.1.3 and on the patched source (macOS,
the Command Line Tools as in `build-macos.sh`), and compare:

```bash
cd ~/4_dev/mist_dewpoint-celbackport
T=$(mktemp -d ~/cel-upstream-tests-XXXX)
deploy/cel-runtime/prepare.sh "$T/patched"
git clone -q https://github.com/cel-expr/cel-python.git "$T/stock" && git -C "$T/stock" checkout -q 3e369fe3dfd29ef2fcb3d8a63997e58f50e592ae
for tree in stock patched; do
  (cd "$T/$tree" && DEVELOPER_DIR=/Library/Developer/CommandLineTools USE_BAZEL_VERSION=8.5.1 \
    BAZELISK_VERIFY_SHA256=cb6d2f19ad92157e7186f64151e665c1b0c3bacaa690784e66f446f1b7660140 \
    BAZELISK_HOME="$T/bazelisk-home" "$OLDPWD/deploy/cel-runtime/bazelisk-darwin-arm64" --output_user_root="$T/root-$tree" \
    test //cel_expr_python/... --action_env=DEVELOPER_DIR --host_action_env=DEVELOPER_DIR > "$T/$tree.log" 2>&1)
  echo "$tree: exit=$?"; grep -E '^//.* (PASSED|FAILED|NO STATUS)' "$T/$tree.log" | sort > "$T/$tree.results"
done
diff "$T/stock.results" "$T/patched.results" | grep -v -E 'in [0-9.]+s$' ; wc -l "$T"/*.results
```

Expected: the patched source fails no test that v0.1.3 passes (the `diff` shows timing only). Record both counts in
the ledger, then delete `$T` and `deploy/cel-runtime/bazelisk-*`. A new failure is a defect in the patch: stop and
bring it to the owner.

- [ ] **Step 4: Local CodeQL**

Mirror CI's `analyze (python)` (its CLI 2.27.2 and `codeql/python-queries` 1.8.12, the workflow's
`exclude-from-incremental` filter). On this network Zscaler intercepts `ghcr.io`: give the bundled JVM a scratch trust
store with the Zscaler root, never a system change.

```bash
gh codeql set-version v2.27.2 && gh codeql pack download codeql/python-queries@1.8.12
S=$(mktemp -d ~/codeql-XXXX); mkdir "$S/src"
git archive HEAD | tar -x -C "$S/src"
D=$(dirname "$(gh codeql resolve languages --format=json | python3 -c 'import json,sys; print(json.load(sys.stdin)["python"][0])')")
cp "$D/tools/osx64/java-aarch64/lib/security/cacerts" "$S/cacerts"
security find-certificate -c "Zscaler Root CA" -p /Library/Keychains/System.keychain > "$S/zscaler.pem"
"$D/tools/osx64/java-aarch64/bin/keytool" -importcert -noprompt -alias zscaler -file "$S/zscaler.pem" -keystore "$S/cacerts" -storepass changeit
printf 'query-filters:\n  - exclude:\n      tags: exclude-from-incremental\n' > "$S/config.yml"
gh codeql database create "$S/db" --language=python --source-root="$S/src" --codescanning-config="$S/config.yml" \
  -J=-Djavax.net.ssl.trustStore="$S/cacerts" -J=-Djavax.net.ssl.trustStorePassword=changeit
gh codeql database analyze "$S/db" --format=sarif-latest --output="$S/out.sarif" \
  -J=-Djavax.net.ssl.trustStore="$S/cacerts" -J=-Djavax.net.ssl.trustStorePassword=changeit
python3 -c 'import json,sys; print(sum(len(r["results"]) for r in json.load(open(sys.argv[1]))["runs"]))' "$S/out.sarif"
```

Expected: `0`. Then delete `$S`. If the CLI's layout differs from these paths, find `cacerts` and `keytool` under
`$D/tools` and use those.

- [ ] **Step 5: The Compose proof**

Run the `e2e` job's steps from `.github/workflows/ci.yml` locally in `deploy/compose` (its `.env` lines, the dev CA,
`docker compose up -d --build --wait`, `admin init`, "The worker's build is current", and the steps after it). Then:

```bash
cd deploy/compose
docker compose exec -T cel-evaluator /app/.venv/bin/python -c 'import importlib.metadata as m; print(m.version("cel-expr-python"))'
docker compose logs cel-evaluator | grep -m1 'serving'
docker compose down -v
```

Expected: every step passes; `0.1.3+dewpoint.1`; the evaluator serves `cel-cpp-0.1.3+dewpoint.1/fn-1/cls-1` (Review
Focus 2 against a real Temporal server).

- [ ] **Step 6: Record the results in the ledger**

Append to `~/4_dev/mist_dewpoint-2b4b-m4/ledger.md`: each step's command and result, the census numbers, and the
branch's commits.

## After this plan

Each needs the owner's go, and none is a task here:

1. Push `fix/cel-backport` and open one PR for ABI 8 (#16's commit and this plan's), whose description cites Task 5's
   evidence; the session that owns #16 is told.
2. CI: `cel-gates` on x86 is the gate's measurement. A failure over 1.0 s is a real failure, never re-run to green.
3. The x86 warmed-worker comparison (handoff steps 5–6): rebase `diag/cel-gate-activations` onto the branch and
   dispatch its `warm-worker` job, each dispatch on its own go.
4. When the ABI 8 build is current everywhere and the old runs have drained: retire `cel-cpp-0.1.3/fn-1/cls-1`.
