# The CEL evaluator: deployment and operation

Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §5.7.

The `cel-evaluator` evaluates the CEL expressions that don't run inline in a workflow ("Runs as a separate step" in
the editor). It holds no secrets and has no network: the CEL activity worker reaches it through a Unix socket on a
volume that only the two of them mount.

Publish sends it the expressions too costly to run inline. At run time, any expression whose inputs exceed the inline
caps comes here too: a list or map over 200 entries, a string over 16 KiB, or more than 64 KiB of JSON. The list and
map caps are low because the CEL runtime's memory for `map` and `filter` grows with the square of the list's length
(spec §5.5). Workflows over large lists therefore depend on the evaluator: size its slots for them.

**Docker Compose only, for now.** That socket only works between containers on one host. In Kubernetes the evaluator
must be its own pod. It can't be a sidecar in the worker's pod, which would share the worker's network and egress.
Its own pod needs a network transport: authenticated (mTLS), admitted only from the CEL worker's pods by a
NetworkPolicy that also denies all egress, and with no Kubernetes API access. That design comes with the Helm chart
(spec §5.7, §12). Until then, a Kubernetes deployment can't run the expressions that need the evaluator.

## What it refuses

It exits with status 2 and says why when:

- **its environment holds anything unexpected.** It accepts only `DEWPOINT_CEL_SOCKET` (default
  `/run/dewpoint-cel/cel.sock`), `DEWPOINT_CEL_MAX_SLOTS`, `DEWPOINT_CEL_CGROUP` (default `/sys/fs/cgroup`),
  `DEWPOINT_CEL_PROFILE`, and variables the OS, the container runtime or the Python base image set (`PATH`, `HOME`,
  `HOSTNAME`, `LANG`, `PYTHON_VERSION`, …). Never pass it database, Temporal, KEK or tenant-key settings.
- **its cgroup has no memory limit**, or the limits leave fewer than one evaluation slot.
- **it isn't Linux** (it relies on rlimits and cgroup v2).
- **`DEWPOINT_CEL_PROFILE` is set and differs** from the profile the image's runtime gives
  (`cel-cpp-<runtime version>/fn-1/cls-1`).

## Sizing

The evaluator reads its own cgroup limits at start and derives its concurrency:

- **N = min(CPUs, ⌊(memory limit − 256 MiB) / 264.25 MiB⌋)**, lowered by `pids.max − 8` and by `DEWPOINT_CEL_MAX_SLOTS`,
  never raised.
- Each slot is one child: `RLIMIT_AS` 256 MiB, `RLIMIT_CPU` 5 s, 16 descriptors, no file writes, no core dumps, and a
  5 s wall-clock kill. The 8.25 MiB per slot covers one in-flight request, one queued request and one response.
- At most N children run, with N more queued; beyond that the answer is `busy`, which the activity retries. Set the
  CEL worker's `max_concurrent_activities` to N so that doesn't happen.

Compose gives it 2 GiB, 2 CPUs and 14 pids: N = 2. Give it more CPUs (up to 6 at 2 GiB) for more concurrency, and
keep `pids_limit` at N + 8.

## Health

`python -m dewpoint.apps.cel_evaluator --health` exits 0 when the local evaluator answers with this image's profile.
Compose uses it as the healthcheck.

## Profiles

One evaluator serves one CEL profile. Keep an evaluator for a profile running while any active, queued or running
workflow version uses it (`docs/operations/plugin-lifecycle.md`). A request for another profile fails closed
(`profile_mismatch`, then the step's error is `cel_profile_unavailable`); no other profile ever evaluates it.

## Outcomes

Every evaluation ends in a value or a recorded outcome, never a retry: `timeout`, `cpu_limit`, `memory_limit`,
`iteration_budget_exceeded`, `type_mismatch`, `evaluation_error`, `non_json_value`, `output_too_large`,
`input_too_large` or `evaluation_crashed`. Only infrastructure failures are retried: the socket is unreachable, the
connection drops, or the answer is `busy`.
