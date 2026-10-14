# Input nesting (issue #88): a limit at every entry, and validators that never raise

Branch `fix/input-nesting` from `origin/main` 90f4fe4, on the owner's choice of #88 (2026-10-14). A plan for the
owner's rulings; nothing is built until the owner's go, and nothing is committed without it.

## Facts (measured 2026-10-14, CPython 3.12, recursion limit 1000; never from memory)

- `apps.inputs.reasons()` under #88's recursive schema raises `RecursionError` from 248 levels, in the main thread and
  in a thread of the default stack size; at 64 levels it validates cleanly.
- `json.loads` raises `RecursionError` from 9,998 levels. FastAPI 0.141.1 (`fastapi/routing.py`) answers a body it
  can't parse with 400 "There was an error parsing the body", so an API route sees inputs up to about 9,997 levels.
- `json.dumps` raised nothing up to 5,000 levels.
- Precedents: `engine.graph.model.MAX_DEPTH` = 64 (a workflow document, checked iteratively before anything else) and
  `core.ingress.parsing.MAX_DEPTH` = 64 (a webhook body, iteratively, "so an event's depth never depends on an
  interpreter's recursion limit").
- Stored inputs: a schedule's (sealed, `schedules.input`), and a run's own, kept for re-runs as encrypted claims and
  an envelope (`run_inputs`), which `original_input()` (`apps/api/routes/run_requests.py`) rebuilds; a request keeps a
  digest. A webhook run's input is its event as parsed (`dispatcher/matching.py`), so at most 64 levels already.
- Claims bound the count of nested claims (`engine.handles.NESTING_MAX` = 32), not the depth they expand to: resolving
  (`resolve_value()`, its `_plain()`) recurses a level of data at a time through every claim, so claims each well
  under 64 levels expand past the recursion limit (the owner's review of this plan reproduced `RecursionError` in the
  sub-flow crossing, before `reasons()`, from a two-level envelope naming 24 claims each 41 levels deep).
- Claim discovery recurses too: `engine.handles.handles_in()` is a recursive generator, a level of data a frame, and
  the crossing's `_walked()` reaches it through the store's `read_level()` (`apps/worker/store.py`; `nested()` too), so
  one stored claim deep enough fails before any resolver runs (the owner's second review reproduced it with a
  two-level envelope naming one 2,000-level claim).
- `resolve_value()` serves eight callers (`apps/worker/claims.py`: a step's config, a loop's items, a failure's
  strings, a child's input; `apps/api/routes/run_requests.py`: a re-run's rebuild): a cap there for all of them would
  change what resolves today (a step config holding a claimed 65-level body resolves). The crossing turns
  `ClaimUnavailableError` and `NestingError` into `claim_unavailable` (`UNREADABLE`).
- The schedule-break warnings (`apps/schedule_checks.py`, validate and publish) report no break for a stored input
  65 levels deep under a permissive schema, though admission would refuse every firing past the limit.

## Where an input enters

1. An API start, re-run or dev run: admission (`apps/admission.py`) calls `inputs.claim_input()`, which calls
   `checked()`: `reasons()`, then the marker check, then `split()`.
2. A schedule's create or replace: `apps/schedules.py` `_checked_input()` calls `reasons()` (an uncaught
   `RecursionError` there is a 500, by reading; a test will show it).
3. A schedule's firing: admission again, on the stored input, under the version active then.
4. A webhook's firing: admission, the event at most 64 levels.
5. A sub-flow's start: `apps/worker/claims.py` walks the child's claims, resolves the input (`resolve_value()`),
   then calls `reasons()`, in the worker; a `RecursionError` in either is an unexpected activity error, not a refused
   input.
6. A re-run of a run without a new input: `original_input()` rebuilds the retained input (`resolve_value()` again),
   then admission (1).

## Proposed rulings

- Ruling 1: an input nests at most 64 levels of objects and arrays, its own value the first: the engine's limit for a
  document, counted as the webhook parser counts, iteratively - cost if wrong: an input deeper than 64 levels can't
  start a run (a webhook's already can't).
- Ruling 2: the limit is checked first, before anything recursive, at entries 1 to 6, and refused with one fixed
  reason, "The run's input nests deeper than 64 levels." (code `input_invalid`): an API start, a re-run, or a
  schedule's create or replace answers 422 `input_invalid` with it; a firing records a `refused` request with the code
  `input_invalid` (a durable refusal keeps its code, never its messages), as any input the active version refuses; a
  sub-flow's crossing returns it as the child's refused input, so the parent's step fails as for any refused child
  input - cost if wrong: none.
- Ruling 2a (the reviews' Mediums): at the two boundaries where a run's values become an input, the child's crossing
  and a re-run's rebuild, the depth is bounded through claims, and only there:
  - claim discovery never recurses: `handles_in()` walks iteratively, yielding the same handles in the same order
    (outermost first), so discovery is unchanged for every caller and no stored claim's depth can fail it;
  - `resolve_value()` takes an opt-in bound (`max_depth`, none by default): given one, it counts the levels of the
    value it builds across every claim and stops past it, never descending further, raising a distinct
    `InputTooDeepError` (never `NestingError` nor `ClaimUnavailableError`, so never `claim_unavailable`); the other six
    callers pass none and resolve as today;
  - the crossing checks the envelope first, discovers its claims, resolves under the bound (64), then validates; the
    rebuild resolves under the bound; each turns `InputTooDeepError` into the fixed reason.
  Cost if wrong: a value deeper than 64 levels in a run can't cross into a sub-flow, nor be rebuilt for a re-run; any
  wider bound (step configs, items, failure strings) is a separate proposal for separate approval.
- Ruling 3: `reasons()` never raises `RecursionError`: it answers a fixed reason, "The run's input is nested too deeply
  to check against the workflow's input schema." (defense in depth for a schema that spends many frames a level) -
  cost if wrong: none.
- Ruling 4: no migration, and no change to existing runs, requests or claims, for inputs already stored deeper: a
  schedule's firing is a refused request naming the reason, and replacing its input fixes it; a re-run of a run whose
  retained input is deeper is refused with the reason (422), and a re-run given a replacement input proceeds - cost if
  wrong: such a schedule fires refused, and such a run re-runs only with a new input, until someone changes it.
- Ruling 5 (the review's second Low): the schedule-break warnings take the depth rule as a structural break: a stored
  input deeper than 64 levels is a schedule that breaks, said as such, within the check's existing bounds
  (`MAX_CHECKED`, `MAX_INPUT_BYTES`, its step budget) and as a warning only - cost if wrong: none.

## Tasks (test-first; each test watched failing, each protection mutation-checked)

1. One iterative depth check beside `reasons()` (`apps/inputs.py`), the limit `engine.graph.model.MAX_DEPTH`; tests at
   63, 64 and 65 levels, arrays and objects, and the same count as `core.ingress.parsing` (an event it accepts passes).
2. `checked()` and `schedules._checked_input()` refuse past the limit first; `reasons()` turns `RecursionError` into
   its fixed reason. Tests: an API start, a schedule's create and replace past the limit answer 422 (not 500); a
   stored schedule's firing is a refused request with the reason; `reasons()` at 300 levels answers instead of
   raising.
3. The crossing's bound (ruling 2a): `handles_in()` iterative, its yields and order unchanged (a test against the
   recursive version's output on nested handles); `resolve_value(..., max_depth=)` opt-in with `InputTooDeepError`;
   the crossing envelope first, then discovery, then the bounded resolve. Regressions, each refused with the reason,
   never a `RecursionError` nor `claim_unavailable`: a raw-deep child input (65 levels, and 300); a claim-expanded one
   (a two-level envelope naming claims each under 64 levels whose expansion passes 64, as the first review's 24 claims
   of 41 levels); an individually deep stored claim (a two-level envelope naming one claim of 2,000 levels, as the
   second review's). Unchanged elsewhere: a step config holding a claimed 65-level body resolves as today. One
   through RunGraph: the parent's step fails with the child input refused, the reason named.
3a. Re-runs: a re-run of a run whose retained input is 65 levels deep (and one 300 deep) answers 422 with the reason;
   a re-run of it given a replacement input proceeds; the old run's rows, request and claims are unchanged.
3b. The schedule-break warnings: a stored 65-level input under a permissive schema is reported (a warning, never a
   refusal), one at 64 isn't, and the check's bounds hold (a test past `MAX_CHECKED` and `MAX_INPUT_BYTES` as today).
4. A recursive schema at exactly 64 levels validates without `RecursionError` in the main thread and in a worker
   thread (counted in levels, not time).
5. Docs where the run input's rules are written, and this plan's record: runs, review, checkpoint.

Then a fresh-context review hunting fail-open paths, fixes test-first, the affected suites, gitleaks, local CodeQL, a
checkpoint; the full suite, commits, push and PR each on the owner's go.

## Not in scope

API bodies deeper than about 9,997 levels (already 400), webhook bodies (already 64), and values inside a run deeper
than 64 anywhere but a sub-flow's crossing and a re-run's rebuild.

## Reviews

- The owner's technical review of this plan (pasted, 2026-10-14, against 90f4fe4): one Medium (bound the sub-flow's
  claim expansion: reproduced before `reasons()`), two Low (retained inputs for re-runs beside schedules; the
  schedule-break warnings miss the depth rule); the 64-level choice supported (the existing checks agree at 63, 64
  and 65; the recursive schema validates at 64 in the main and a default-stack thread). Folded in above: ruling 2a,
  rulings 2, 4 and 5, entry 6, tasks 3, 3a and 3b. No build authorization, no ruling sign-off.
- The owner's second technical review (pasted, 2026-10-14): the two Lows incorporated; two Mediums in ruling 2a: claim
  discovery (`_walked()` → `read_level()` → recursive `handles_in()`) fails before the bounded resolver on one deep
  stored claim; an unconditional cap in the shared `resolve_value()` changes behavior outside this slice (step
  configs, items, failure strings). Both checked in the code and folded in: ruling 2a rewritten (iterative discovery,
  an opt-in bound at the two boundaries, a distinct `InputTooDeepError`), task 3's regressions extended. No build
  authorization, no ruling sign-off.

## Build (2026-10-14, on the owner's "go, build it"; uncommitted until the owner's go to commit)

Tasks 1 to 5 built test-first, each test watched failing (or, for a protection already present, its removal
watched failing), each protection mutation-checked:
- Tasks 1 and 2 (`apps/inputs.py`, `apps/schedules.py`): `nests_too_deep()`, `checked()` and `_checked_input()` depth
  first, `reasons()` answering `TOO_DEEP_TO_CHECK`; tests at the decoder level, an API start and re-run, a schedule's
  create and replace, and a stored schedule's firing (300 levels under a recursive schema, 65 under a permissive one,
  64 queued); 6 mutants killed.
- Task 3 (`engine/handles.py`, `apps/worker/claims.py`): `handles_in()` iterative (a property test against the
  recursive version), `resolve_value(max_depth=)` and `InputTooDeepError`, the crossing envelope first; tests for a raw
  65-level child input (no claim read), the first review's 24 claims of 41 levels, the second review's one claim of
  2,000 levels, 64 levels through two claims crossing, and one through RunGraph (two echoes nesting 81 levels: the
  parent's step fails `input_invalid` with the reason, the child never starts); 8 mutants killed.
- Task 3a (`apps/api/routes/run_requests.py`): the rebuild bounded; re-runs of kept 65- and 300-level inputs refused,
  a new input recovering, nothing kept changed; a kept root claim resealed at 2,000 levels refused (it was a 500); 2
  of 3 mutants killed, the third (admission's own check) being the same refusal the bounded rebuild gives first,
  killed by the start and firing tests.
- Task 3b (`apps/schedule_checks.py`): a stored input past the limit is a break, CSV first; the API's validate and
  publish (the final review's 300-level input stored directly: the API refuses it now); 2 mutants killed.
- Measured on the way: `split()` breaks at 498 levels and the unbounded resolver at 988, so no admission could keep an
  input deeper than 497 levels (a start that deep was an unexpected error, which the depth-first check now prevents).
- Task 5: `docs/operations/runs.md` (admission, the input's check, the sub-flow crossing, the `input_invalid` code).

A fresh-context review of the build (2026-10-14): no High, no Medium, no fail-open path; six Low, each fixed
test-first and mutation-checked (7 mutants killed), but L6 (a note):
- L1: the crossing's envelope check counted a handle object as a level, so 64 levels whose deepest leaf the parent
  claimed (a spilled string, a sensitive value) were refused though they resolve to 64. Ruling: at the crossing a
  handle counts as the leaf it stands for (`nests_too_deep(handles=True)`); the bounded resolver counts what it expands
  to; an input from outside holds no handle (the marker is refused) - cost if wrong: none.
- L2: an exact retry's idempotency digest was computed before the input's depth was read (a re-run's identity wraps
  the input 2 levels deeper). Through the API here the body stops parsing first (409 up to 9,973 levels, 400 from
  9,974: no 500 band), but directly an input of 20,000 levels raised `RecursionError`. Ruling: an interactive
  admission reads the depth before the key (`admit_request`, `admitted_under`; the route answers the latter's refusal
  422), so a too-deep input under a used key is 422 `input_invalid`, not 409 - cost if wrong: such a retry learns the
  input's fault before the key's.
- L3: the schedule check's `RecursionError` fallback lost its test; measured reachable within the limit (64 levels
  under a draft wrapping each level's reference in 6 nested `allOf`: counted unchecked; admission answers it
  `TOO_DEEP_TO_CHECK`): tested again, the docstring corrected.
- L4: publish warned of a depth break as the draft's ("Publishing this would make…"). Ruling: its own warning,
  `schedule.input_too_deep`: those schedules fail at every firing already, and only a new input mends them - cost if
  wrong: none.
- L5: wording: a test said the earlier `RecursionError` was answered as an unusable key (it was a 500); ruling 2 said a
  firing records the reason (only its code is kept: corrected above); a test's name claimed more than it can check.
- L6: the tick test's 300-level case would be refused by `reasons()`' own fixed reason too; its 65-level case is the
  one the depth check alone decides (said in its docstring).
- Noted, not changed: a re-run of a too-deep kept input now answers 422 before admission's workflow checks (gate off,
  disabled), as a missing kept input already answers 410 before them.

The owner's technical review of the build (pasted, 2026-10-14, the uncommitted snapshot): the earlier findings closed,
no new finding, no fail-open path; 303 input-focused checks passed (243 existing tests, 60 independent checks), and
removing either core protection fails the independent checks again. A dispatcher timing test failed in a combined run
and passed alone, as `test_start_rounds` did here: consistent with the dispatcher's one-second pass budget under load,
but the cause isn't established (this machine's load average was 13 to 15 from other work, not only a concurrent
CodeQL run). Technical closure only: no ruling sign-off, no go to commit or publish.

The owner signed off rulings 1 to 5 and 2a, the review's L1, L2 and L4 included (2026-10-14: "1. yes 2. yes 3. yes
4. yes"), and authorized the commits, the full suite, push and PR.
