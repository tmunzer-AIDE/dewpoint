# Editor UI 4d-1a: the Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 7, 2026-10-13.** Nothing is built before the owner approves this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat. Reviews pasted in chat held revision 1 for five findings and a smaller one,
asking for the rulings that change the spec to be treated explicitly, revision 2 for two findings, revision 3 for
three and a defect in a documented alternative, revision 4 for two and a gap in that alternative, revision 5 for
three, that alternative again, and a restriction the spec didn't state, and revision 6 for one and what declining
ruling 16 would do; the "Changes from revision N" sections say how each was answered.

The plan's code was checked before review on a scratch copy of main at d4ab0dbe, never on a branch. Each task's two
diffs were applied as written, in order:
- the test diff alone, then the task's tests: they failed as its "Run them" step says;
- then the implementation diff, the golden histories recorded where the task says, and the same tests: they passed;
- after every task, ruff (check and format), mypy on `src` and the import contracts (11 kept): clean;
- after the last, the tree matched the prototype the diffs were cut from, file for file;
- the 18 diff blocks, taken from this file's own text, apply in order onto d4ab0dbe and give each task's tree
  exactly.

On revision 1's last tree, the worker and dispatcher suites were started, then stopped at about a fifth: they were on
course for 15 minutes, past the 10 a run may take unasked. About 230 had passed, none had failed. The whole backend
suite wasn't run; Task 11 runs it, with the owner's OK. The executor still runs every step: the check is evidence, not
a substitute.

## Changes from revision 6

It answers the review of revision 6, pasted in chat on 2026-10-13. The new test below fails on revision 6's code and
passes on revision 7's.

1. **P2, a non-null guard's condition was lost.** The contract carried only `has()` facts, so with `trigger.owner`
   read whole beside `trigger.owner.profile != null ? trigger.owner.profile.name : 'absent'`, `{"profile": null}`
   was refused ("must hold /profile/name"), though the run takes it; mapped through a filter, likewise. The contract
   now also asks the validator's non-null and object facts (`guards.facts_at` with `guards.non_null` and
   `guards.shape`), and a use keeps them apart from its presence facts: they condition what it reads below (a hold
   is now worded "where … is there and isn't null"), and never excuse an absence, since `x != null` fails where `x`
   is missing. The comparison still reads `profile` itself, so `{}` is refused, and so is a `profile` without
   `name` (Task 8; ruling 2). Test: `test_a_read_a_non_null_test_guards_holds_only_where_that_isnt_null` (revision 6:
   `{"profile": null}` refused, merged and mapped).
2. **Conditional, declining ruling 16 turned a known-wrong admission back on.** Revision 6 said to keep nothing and
   take the strict case. Declining it now stops the executor at Task 8, as for ruling 2: a filter over a computed list
   then needs its own plan (Task 1).

## Changes from revision 5

It answers the review of revision 5, pasted in chat on 2026-10-13, whose core was: keep a read's conditions when it's
mapped onto a list or merged into an outer value, rather than making it unconditional or dropping it. Each new
contract test below fails on revision 5's code and passes on revision 6's; the run-time test passes on both.

A value's holds are now conditional (`Hold(pointer, given)`): the first `given` segments are a condition, where
they're there, and the rest must be. A guard's read is held where what the guard proves present is; a filter's read of
each element is held where the list is, and needs nothing of an empty one. A hold follows a list index as one, and
reads `*` as each element (Task 8; ruling 2).

1. **P2, a filter whose `items` went through an index refused its own inputs.** With `items =
   ref(trigger.groups[0].aps, default=[])`, `[{"aps": [{"mac": "m"}]}]` and `[]` failed `/0/aps/*/mac`. The hold now
   follows `0` as an index, and `/0/aps` is its condition: missing, the default applies. Test:
   `test_a_filters_reads_through_its_items_keep_their_conditions` (revision 5: both refused).
2. **P2, mapping a predicate's reads made a list its items default non-nullable.** A read of each element takes a
   null, or absent, list at or above where it reads each element: a null list has none, and a default takes its
   place (`_Use.takes_null`). Tests: the same, with `/trigger/aps = null` (revision 5: "This value can't be null."),
   and, at run time, `test_a_filter_alone_over_a_null_list_takes_its_items_default`.
3. **P2, merging lost a guarded read's condition.** With `trigger.boss` read whole beside `has(trigger.boss.profile) ?
   trigger.boss.profile.name : 'absent'`, revision 5 took `{"profile": {}}`, which then failed the step. The hold is
   now `/profile/name where /profile is there`: no `profile` is fine, a `profile` must hold `name`. Test:
   `test_a_guarded_read_inside_a_value_holds_only_where_its_guard_is_there` (revision 5: `{"profile": {}}` taken).
4. **Conditional, the types-only alternative was still unsound.** Excusing a whole `not` or `contains` error for a
   value rule inside it drops the types beside that rule (`not: {anyOf: [{type: "string"}, {enum: [99]}]}` took
   `"x"`). Reading those right needs `not` and `contains` read three ways, a value rule inside them being neither
   true nor false. This plan doesn't build that, so the alternative is withdrawn: if the owner drops ruling 2's value
   rules, Task 8 is planned again (ruling 2).
5. **The computed-list restriction is now a ruling, and narrower.** Keeping the schema's `required` where a filter's
   items are computed is a change to §5.2, so it's ruling 16, with its spec text in Task 1. It now applies only when
   the predicate reads an element strictly; a guarded or defaulted predicate needs nothing (`has(item.mac) && item.mac
   == 'm'` over `trigger.aps + []` takes `[{}]`). Test: `test_a_computed_list_keeps_required_only_for_a_strict_read`
   (revision 5: refused).

## Changes from revision 4

It answers the review of revision 4, pasted in chat on 2026-10-13. Each new contract test below fails on revision 4's
code and passes on revision 5's; the run-time test passes on both.

1. **P2, a filter's predicate reads bound nothing in the list it filters.** `item.mac == "m"` took `/trigger/aps =
   [{}]`, which then failed the step, since `item` reads were left out of the contract with their obligations. They
   still aren't seeds, but when the filter's `items` is a path (a ref, or a CEL value that's only a path), each
   predicate read of `item…` is now a read of every element of that list (`EVERY`, shown `*` in a pointer). A strict
   one makes every element hold it (`/*/mac`); a guarded one makes none; a default makes null fine there. When the
   items are computed (`trigger.aps + []`), a predicate read can't be traced to a seed, so the entries the items read
   keep their schema's `required` (Task 8; ruling 2). Tests:
   `test_a_filters_predicate_reads_bind_each_element_of_the_list_it_filters` (revision 4: `[{"mac": "m"}, {}]` and
   the computed list both taken), and, at run time,
   `test_a_filter_alone_takes_elements_its_guarded_predicate_reads_nothing_of`.
2. **P2, `oneOf` refused a null its uses take.** With the null excused, both of `profile`'s branches were clear, and
   revision 4 asked `oneOf` for exactly one. What's excused stands for a value the run supplies, and a real value
   there picks its own branch, so a choice now passes when any branch is clear once excused, `oneOf` as `anyOf`. A
   value valid under two branches with nothing excused is still refused: jsonschema reports it with no branch errors.
   Test: `test_a_null_a_default_takes_stands_for_a_value_that_picks_its_own_branch` (revision 4: "Matches none of the
   forms its schema allows.").
3. **Conditional, the types-only alternative still refused a negated enum.** `not: {"enum": ["blocked"]}` reports as
   `not`. The alternative (Task 1) now also excuses a `not` or `contains` error when its subschema holds a value rule
   anywhere: the test then depends on a value. One of types alone still refuses. Tried on revision 5's code: a
   negated enum and a `contains` of a `const` are taken; `not: {"type": "string"}` and a `contains` of a type refuse
   as before, and so does a type beside the negation.

## Changes from revision 3

It answers the review of revision 3, pasted in chat on 2026-10-13. Each new test below fails on revision 3's code and
passes on revision 4's. Revision 3 removed `required` from a seed's schema before checking it; revision 4 checks the
schema as it stands, and excuses only the errors §5.2's uses make none: a presence the schema obliges and a null the
uses take, judged branch by branch inside a choice (Task 8; ruling 2).

1. **P2, removing `required` changed what `not` and `if` test.** `not: {"required": ["name", "age"]}` became `not:
   {}`, refusing every value, and `if: {"required": ["mode"]}` became always true. They now keep their meaning: their
   errors are `not`'s and `then`'s or `else`'s own, never a presence excused. Test:
   `test_presence_tested_by_a_schema_keeps_its_meaning` (revision 3: both refused).
2. **P2, a null the uses take was refused inside `anyOf`.** The choice reported one error for the containing value.
   A failing `anyOf` or `oneOf` is now judged by its branches (jsonschema's `context`, by branch index): it passes
   when a branch has no error left once these are excused (for `oneOf`, exactly one). Other errors still refuse.
   Test: `test_a_null_the_uses_take_is_taken_inside_a_choice` (revision 3: "Matches none of the forms its schema
   allows.").
3. **P2, a read through a list index lost its default's allowance.** `ref("trigger.aps[0].mac", default=…)` reads
   `/0/mac` inside the whole list it's promoted to; revision 3 derived the allowances from the promoted path alone.
   Each use now keeps what it reads before the cut (`_Use.read`), and null is taken at `/0/mac`, not at an element
   no use reads. Test: `test_a_read_through_an_index_keeps_its_allowances_in_the_whole_list` (revision 3: "At
   /0/mac: Must be a string.").
4. **Conditional, the types-only alternative would have dropped types.** Removing `additionalProperties` also removed
   a schema-valued one, such as `{"type": "integer"}`. The alternative (Task 1, if the owner drops ruling 2's value
   rules) now excuses those rules' errors instead: jsonschema reports a closed object as `additionalProperties`, and a
   schema-valued one by its own keywords, `type` among them, so types stay checked. Tried on revision 4's code: a
   value outside an enum and an extra key on a closed object are taken; `{"x": "s"}` under `additionalProperties:
   {"type": "integer"}` is refused.

## Changes from revision 2

It answers the review of revision 2, pasted in chat on 2026-10-13. Each new test below fails on revision 2's code
and passes on revision 3's, except where it says it passes on both.

1. **P2, inside a value, presence and null came from its schema, not its uses.** `/vars = {"n": null}` was refused
   where `vars.n`'s only read has a default, and `/trigger/owner = {}` was refused with "Needs `name`" where `name`'s
   only read has a default; the run takes both. A value is now checked against its schema without the keywords that
   make a field present (`required`, `dependentRequired`), at every place a schema stands. Presence inside it comes
   from the uses (`holds`). Null is taken where the schema allows it, or where every use through that place has a
   default. Types and value rules are still checked (Task 8; ruling 2). Tests:
   `test_inside_a_value_presence_and_null_come_from_the_uses_never_the_schemas_required` (revision 2: "Needs
   `name`."), and, at run time, `test_a_value_whose_inner_read_has_a_default_runs_without_it_or_with_null` (it
   passes on both: the run took these values already; the contract refused them).
2. **P2, an absent `/item` lost its loop's frame.** `has(loops.l.item)` failed with `Key not found in map : "l"`.
   Inside a loop, the seeds' view now always has the innermost loop's frame, empty when neither `/item` nor `/index`
   is given: no item is made up and no index asked for (Task 9). Tests:
   `test_an_absent_item_leaves_its_loops_frame_in_place` (revision 2: that error),
   `test_an_absent_item_leaves_its_loops_frame_empty`.
3. **Ruling 2 no longer narrows §5.2 silently.** Its type checks stay; its check of value rules (enum, pattern,
   bounds, closed objects), which §5.2's "type" doesn't name, is now marked as a change to the spec, for the owner to
   accept or drop like rulings 3 and 13. Task 1 amends §5.2 only if it's accepted; if it's dropped, Task 8 removes
   the value rules too and checks types alone.

A run-time test now pins ruling 1 as well: `test_a_guarded_read_of_a_required_field_runs_with_it_absent` (absent
`/trigger/x` under `has(trigger.x)`). It passes on revision 2 too: the run took it already.

## Changes from revision 1

It answers the review of revision 1, pasted in chat on 2026-10-13. Each new test below fails on revision 1's code and
passes on revision 2's.

1. **P1, a loop open across a continue-as-new ended `not_started`.** The snapshot carried a start only for sleeping
   timers, so the continued execution didn't know that a loop still open there had begun. A cancel then rowed it
   `not_started` (its first start kept by the upsert, beside a status saying it never began).
   The snapshot now carries every open loop's start and CEL mode, as a timer's (Task 5; ruling 15). Test:
   `test_a_loop_open_across_a_continue_as_new_ends_cancelled_with_its_first_start` (revision 1: `not_started`).
2. **P1, a step that reads only its item couldn't run alone.** The resolver and CEL's binding both took an item to be
   in scope only with an index, so `/item/n` alone failed "`item.n` has no value here". `ScopeView` gains `framed`:
   an item in scope without its index. A single step inside a loop is framed; a normal run's views are as before
   (Task 9; ruling 14). Tests: `test_a_loop_contained_step_that_reads_only_its_item_needs_no_index` (a ref and a CEL
   read), `test_the_frame_is_there_without_its_index`.
3. **P2, a value merged with the reads inside it lost their types.** `{"name": 42}` passed for an `owner` whose `name`
   is a string, and a list's elements weren't checked. Each entry now keeps the resolver's schema for it, which is
   self-contained (`standalone` carries the root's `$defs`), and the schema of each read inside it. A value given is
   checked against both with the validator's own `problems()`, as admission checks a run's input
   (`apps/inputs.py`). Ruling 2 says so, and no longer leans on the step's own checks (Task 8). Test:
   `test_a_value_is_checked_against_its_whole_schema_and_each_read_inside_it` (a child, a list's element, a variable
   inside `/vars`).
4. **P2, variables given whole, as one claim, broke the reads of each.** `_base` read `vars.<name>` off the claim's
   marker. A variable is now read through the claim, as any other value past a handle (Task 9). Test:
   `test_the_variables_seeded_whole_as_one_claim_are_each_read_through_it` (revision 1: "`vars.n` has no value
   here").
5. **P2, a projection could carry more than 500 end rows.** The cap held for the rows made per call, not for those
   sent: a byte-cut projection left rows waiting, and the next call added 500. The execution now counts the end rows
   waiting, and never has more than 500 of them (Task 10; ruling 7). Test:
   `test_a_byte_cut_projection_never_sends_more_than_its_end_rows_limit`, counted in rows without a workflow
   (revision 1: 720 in one projection).
6. **A path below an alias was `seed_unknown`.** `/loops/l/item/mac` is now `seed_alias`, naming `/item/mac` (Task 8,
   in `test_the_innermost_loops_item_is_canonical_and_its_alias_refused`).
7. **Ruling 1 narrowed the spec's guarded-absence rule.** It counted a CEL read of an always-present path as strict,
   so `has(trigger.site) ? trigger.site : ''` needed a value. The contract now asks the validator's guard facts
   (`guards.facts_at`, over the record's checked expression) per read, and follows §5.2 exactly: a read tolerates a
   value's absence when a guard proves that value, or something inside it on the read's path, present (Task 8;
   ruling 1). Test:
   `test_a_read_a_guard_proves_present_may_be_absent`.
8. **Rulings 3 and 13 change the spec.** They stay proposed and are marked so. Task 1 amends the spec's §5.2 and §3.6
   to match, only once the owner accepts them.

The review also replayed all 43 abi8 histories. In its combined worker run, two timer tests timed out once and passed
on a fresh server; this plan's runs didn't meet it.

**Goal:** The engine part of 4d-1, at `ENGINE_ABI` 8 with migration 0071:
- every step instance's end is recorded (B4b);
- a simulated attempt never claims a send, and a simulation doesn't wait out flow timers;
- one step of a version runs alone, simulated, from the values it reads (S2's engine part).

**Architecture:**
- **Ends.** The scheduler reports how each instance ended without settling (`take_ends`: skipped, unstarted,
  stopped). The execution makes each a row (`skipped`, `not_started`, `cancelled`), at most 500 per projection.
- **Precedence.** `core.runs.service.upsert_steps` orders rows: `running`, then a provisional close, then a genuine
  end. A retried or late projection never replaces a known end.
- **Simulation.** A simulate run classifies its attempts without the live send's uncertainty, and resolves flow
  timers without waiting.
- **One step.** A run with `RunInput.target_step_id` instantiates only its target, in the root scope. It reads only
  the seeds its step's contract (`engine/graph/seeds.py`) lists, and ends with that step.

**Tech Stack:** Python 3.12; Temporal's Python SDK (the workflow sandbox, replay); SQLAlchemy 2 (async) and asyncpg on
PostgreSQL 16; Alembic, by hand, through `migrations/online.py`; pytest with xdist, Hypothesis and testcontainers.

**Spec:** `docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md`, approved by the owner on 2026-10-13
(99fda408). Its §2–§5, §8 and §9 are this plan's; §6 (B8) is 4d-1b's and §7 (the UI) 4d-1c's.

## Global Constraints

- **`ENGINE_ABI` 7 → 8** (spec §2), in Task 5, the first task that changes a run's commands.
  - Its golden histories (`backend/tests/engine/replay/dewpoint-0.1.0+abi8/`) are recorded there. Tasks 7 and 9 add
    a scenario each and record it.
  - The recorder only adds what the directory lacks: a recorded history is never rewritten.
  - The abi7 and older directories are never touched. The replay gate compares with the merge base, so the abi8 files
    are additions.
- **One migration, 0071** (the ledger's slot), with `down_revision = "0065"` (main's head).
  - It's written by hand, through the online helper (`migrations/online.py`: `online`, `step`, `plain`, `exists`):
    never Alembic autogenerate.
  - Its downgrade refuses while any row records `skipped`, `not_started` or an effect (spec §3.6).
  - Deploy order: the migration first, as for every ABI bump.
- **Grants unchanged.** `run_steps`' table grants cover `effect_preview`. The privilege reference
  (`backend/tests/qualification/reference_rights.json`) needs no change: Task 2 runs its test to show it (ruling 9).
- **Nothing is sent in a simulation.** No new path sends anything. A simulated attempt's outcome is `simulated`, never
  `outcome_unknown`.
- **Logs name an exception's type only, never values.** The one new log line, `step_result_conflict`, carries ids and
  statuses only; Task 3 pins it.
- **No real Mist or SaaS call.** Tests use the testkit and flow plugins, the in-memory store and the database store.
- **Verify, don't remember.** Every library API is checked in the installed package before it's relied on: Temporal's
  history events, structlog's `capture_logs`, SQLAlchemy's `returning`.
- **No API, no frontend.** Nothing under `apps/api` or `frontend/` changes. 4d-1b wires S2 to admission.
- **CI.**
  - Every check runs locally first. Commits and PRs carry no skip marker.
  - Nothing is pushed and no PR is opened without the owner's OK in chat.
  - Ask before any local run expected over 10 minutes.

## Review Focus

These are the inputs and conditions most likely to bite a person using this. Each is pinned by the test named, in
the task that owns the code.

- **A projection that lands after its run ended**, for an attempt whose result was projected before. `_late()` makes
  it a provisional close; the result stands. Task 3:
  `test_a_running_row_projected_after_its_runs_end_never_replaces_its_result`.
- **A cancel with work begun and work queued**: 100 activities running, one held by the in-flight cap. The 100 end
  `cancelled`, with their start; the queued one ends `not_started`, with none. Task 5:
  `test_a_cancel_ends_started_work_cancelled_and_queued_work_not_started`.
- **A failure inside a batch** (a loop of over 100 items runs in child runs). Every step of every iteration that
  opened has its final row. Task 5: `test_inside_a_batch_every_opened_iteration_ends_each_of_its_steps`.
- **A run that ends with over a thousand open instances.** Their rows are spread over projections, 500 at most each,
  never made in one workflow task. Task 10:
  `test_a_run_that_ends_with_many_open_instances_rows_them_over_several_projections`.
- **A value the schema says is always there, which every use defaults.** The person may leave it absent or null to
  see the default: the strictest use wins (spec §5.2). Task 8: `test_a_value_every_use_defaults_may_be_absent_or_null`.
- **An optional field left absent, inside a container the step tests with `has()`.** The container is still there,
  so `has()` is false, not an error. Task 9: `test_an_absent_seed_leaves_its_container_in_place`.
- **A loop still open when the run continues as new**, then cancelled. It began in the first execution, so it ends
  `cancelled`, with its first start. Task 5:
  `test_a_loop_open_across_a_continue_as_new_ends_cancelled_with_its_first_start`.
- **A step inside a loop that reads only its item**, with no index given. It runs. Task 9:
  `test_a_loop_contained_step_that_reads_only_its_item_needs_no_index`.
- **A value of the right type with a wrong child**, such as `{"name": 42}` for an object whose `name` is text. It's
  refused, naming where. Task 8: `test_a_value_is_checked_against_its_whole_schema_and_each_read_inside_it`.
- **A value without a field its schema requires, where the only read of that field has a default.** It's taken,
  null there too, as the run takes it. Task 8:
  `test_inside_a_value_presence_and_null_come_from_the_uses_never_the_schemas_required`.
- **A schema that tests presence (`not`, `if`) or offers a choice (`anyOf`, `oneOf`).** Presence used as a test
  keeps its meaning, and a null the uses take is taken inside a choice's branch. Task 8:
  `test_presence_tested_by_a_schema_keeps_its_meaning`, `test_a_null_the_uses_take_is_taken_inside_a_choice`.
- **A guarded read merged into a value read whole.** The value may leave out what the guard tests; where that's
  given, it must hold what's read below it. Task 8:
  `test_a_guarded_read_inside_a_value_holds_only_where_its_guard_is_there`.
- **A read below a `!= null` test, merged into a value or mapped through a filter.** A null there is fine; an
  object there must hold what's read below it. Task 8:
  `test_a_read_a_non_null_test_guards_holds_only_where_that_isnt_null`.
- **A filter alone, its predicate reading each element strictly or under a guard.** A strict read makes every
  element hold the field; a guarded one takes elements without it. Task 8:
  `test_a_filters_predicate_reads_bind_each_element_of_the_list_it_filters`.
- **A loop's item left absent, tested with `has(loops.<key>.item)`.** The loop's frame is there, empty: `has()` is
  false. Task 9: `test_an_absent_item_leaves_its_loops_frame_in_place`.

## Rulings this plan proposes

These join the ledger as rulings 159 onward once the owner accepts the plan. Each says why, and what it costs if it's
wrong. Rulings 2 (its value rules), 3, 13 and 16 change the spec (§5.2 and §3.6), and say so; the others make it
exact, or settle what it leaves open.

1. **Seed obligations, per use** (Task 8; spec §5.2's "the strictest wins", made exact).
   - The contract compiles each CEL value as validation did (`runtime.compile_checked`, with the record's
     declarations) and asks the validator's own guard facts (`guards.facts_at`) at each read: never a copy of their
     rules.
   - A use tolerates a value's absence when it has a default, when it's a `has()` test of that value, or when a guard
     proves present, wherever it reads, that value or something inside it on its way.
   - A value given must hold what a use reads inside it, up to what a guard proves present there.
   - Null is accepted where the value's schema allows it, or where every use has a default. A validated draft guards
     a read below a value that may be null (`cel.conditional_ref`), so its uses take null there.
   - Cost if wrong: a guard the facts don't prove leaves a value asked for that could be absent; the person gives it.
2. **A seed's value: types and value rules from its schema, presence and null from its uses** (Task 8). Its value
   rules are a change to spec §5.2, which names only a "type"; Task 1 amends §5.2 once the owner accepts it.
   - Its JSON type first, the clearest refusal; a whole number fits `number`.
   - Then the resolver's schema for it, which is self-contained (`standalone`), and each read inside it against its
     own, as the schemas stand. jsonschema checks them, worded with the validator's `explain()`. A child or a list
     element of the wrong type is refused, naming where.
   - Inside the value, presence and null follow §5.2's uses. A path a use reads strictly must be there, where its
     conditions are (`holds`: what a guard proves present or not null, the list a filter reads each element of).
     Null is taken where the schema allows it, or where every use reading through that place takes one: a default,
     or a read of each element of a list at or below it. So two kinds of error are none: a presence the schema
     obliges (`required`, `dependentRequired`), and a null at a place the uses take one. A choice (`anyOf`, `oneOf`)
     passes when a branch has nothing left once those are excused: what's excused stands for a value the run
     supplies, which picks its own branch. `required` inside `not` or `if` keeps its meaning: it tests, it doesn't
     oblige.
   - A filter's predicate reads each element of the list it filters: when its `items` is a path, a predicate read of
     `item…` is one of every element of that list (`/*/mac`), held where the list is. When its items are computed,
     see ruling 16.
   - The value rules (enum, pattern, bounds, closed objects) are checked too, as admission holds a run's input to
     them (`apps/inputs.py`): a value no run could have there tests nothing the run would meet. If the owner drops
     them, Task 8 is planned again: a check of types alone has to read `not` and `contains` three ways (a value rule
     inside them being neither true nor false), which this plan doesn't build.
   - Reads of one pointer by one step resolve to one schema, so the spec's "contradictory types refuse" has no
     reachable case, and gets no branch.
   - Cost if wrong: a seed outside a value rule its schema states is refused; the person gives one that fits it.
3. **Normalized reads, a change to spec §5.2** (Task 8). Task 1 amends §5.2 once the owner accepts it.
   - A read through a list index is the whole list: a seed never builds a list with gaps.
   - A CEL read of `steps` or `loops` that names no step's section reads every step's results, so the step can't run
     alone (`refused`). §5.2's "a whole-container read gives a root entry" stays true of `vars`.
   - Cost: such a step needs Simulate workflow.
4. **Codes beside the spec's** (Tasks 8–9). 4d-1b maps them to its 422 answers. Cost: a renamed code there.
   - `seed_invalid`, beside `seed_missing`, `seed_alias` and `seed_unknown`: a value that breaks its schema, null
     where it can't be, a pointer both given and absent, or a value without a path it must hold.
   - `seed_alias` for a path below an alias too (`/loops/l/item/mac`), naming the canonical one (`/item/mac`).
   - The workflow's guards: `seeded_live_refused` (spec §5.4) and `target_invalid` (the target isn't a step of the
     version, or can't run alone).
5. **An absent seed keeps its containers** (Task 9). With `/trigger/owner/tag` absent, `owner` is still an object, so
   `has(trigger.owner.tag)` is false, not an error. A container the run could lack is read by the step itself, so it
   is its own entry, and its own absence decides. Cost if wrong: a simulation has a container a run might not.
6. **A single-step run never continues as new**, evaluates no declared outputs and starts no failure handler (Task 9).
   One step carries nothing to a next execution. Cost: none expected; a step's attempts are bounded.
7. **End rows lazily, at most 500 waiting** (Task 10; `ENDS_PER_PROJECTION`).
   - They're made as each projection is sent, until 500 wait, those a byte-cut projection left counted. So no call
     makes more than 500, and no projection carries more. A run that ends with thousands of open instances spends
     its rows over several workflow tasks (engine 2b spec §5.3's per-task CPU), never in the activation that ended
     it.
   - 500 sits below a projection's byte cut, about 700 such rows.
   - Cost if wrong: such a run's end takes a few more workflow tasks.
8. **A testkit node for the simulated timeout path** (Task 6): `testkit.slow_simulator`. It's ambiguous; its
   simulator sleeps, and its `run` raises. Test-only.
9. **The privilege reference stays as it is** (Task 2). The spec says the grants go last and the reference is
   regenerated; `effect_preview` falls under `run_steps`' existing table grants, so nothing changes, and its test
   passes as it is. Cost if wrong: the reference test fails, in Task 2 or in CI, and names the right.
10. **The continue-as-new headroom test counts work units, not projections** (Task 5). It ignores `project` units:
    B4b's `running` rows for loops add projections the test never meant to count.
11. **The spread test's loop body is slow** (Task 10). It uses `testkit.slow` for 30 s, a time it never reaches. A
    quick body beside a root failure meets a hang that predates 4d-1a: an `ACTIVITY_UNKNOWN` when a body activity
    completes after the root failed. That's its own task, outside this plan.
12. **A cancel reaches a running activity in about 30 s** (Task 5). No step sets a heartbeat timeout, so the SDK
    sends heartbeats at its default throttle. 4d-1a doesn't change it; the cancel test waits that long.
13. **A build ahead of 0071 drops nothing, a change to spec §3.6** (Task 2). §3.6 says such rows are "dropped with a
    log"; Task 1 amends it once the owner accepts this ruling.
    - Every row the new build projects names `effect_preview`. A database before 0071 lacks the column: SQLSTATE
      42703, which the store doesn't take for a refusal (`apps/worker/store.REFUSED` is classes 22 and 23 only).
    - So the projection fails, and Temporal retries it, every 30 s at most (`PROJECT`'s retry policy has no attempt
      limit), until the migration lands. Rows and run ends wait; none is lost. "Dropped with a log" is how the store
      treats a row the database refuses, which this case never reaches.
    - The deploy order (migration first) avoids the wait. Cost if wrong: none for the data; runs' ends wait.
14. **An item in scope without its index** (Task 9; `ScopeView.framed`).
    - A single step inside a loop is framed: `item` is bound, from its seeds, whether or not `/index` is given (spec
      §5.2 lists only what the step reads).
    - The resolver and CEL's binding read `item` when framed or indexed. A normal run's views never set `framed`, so
      they bind exactly as before.
    - Cost if wrong: none for normal runs; a single step reading `index` it wasn't given still fails `seed_missing`
      first.
15. **A continued run knows which open loops began** (Task 5). The snapshot gains `loops`: each open loop's start and
    CEL mode, as `timers` carries a sleeping timer's. `snapshot_format` stays 2: only an ABI-8 build restores an
    ABI-8 snapshot. Cost if wrong: none; a loop still open across a continue ends `cancelled`, never `not_started`.
16. **A filter over a computed list, a change to spec §5.2** (Task 8). Task 1 amends §5.2 once the owner accepts it.
    - When a filter's `items` is computed (not a path), a strict predicate read of `item…` can't be traced to a seed.
      The values its items are computed from keep their schema's `required` there, as a validated run's values have
      them, so the elements have what the predicate reads.
    - A guarded or defaulted predicate read needs nothing, and keeps nothing.
    - Cost if wrong: a seed that leaves out a field its schema requires there is refused, though the predicate might
      not read it; the person gives it. Without this ruling, such a filter takes elements its predicate fails on.

## File Structure

New:
- `backend/migrations/versions/0071_step_instance_ends.py`: the wider status check and `run_steps.effect_preview`.
- `backend/src/dewpoint/engine/graph/seeds.py`: a step's seed contract, and the seeds checked against it.
- `backend/src/dewpoint/engine/runtime/seeds.py`: a single-step run's seeds, as its scope view.
- `backend/tests/migrations/test_0071.py`, `backend/tests/apps/worker/test_store_precedence.py`,
  `backend/tests/apps/worker/test_run_graph_ends.py`, `backend/tests/apps/worker/test_run_graph_seeded.py`,
  `backend/tests/engine/graph/test_seeds.py`, `backend/tests/engine/runtime/test_seeds.py`,
  `backend/tests/engine/runtime/test_end_rows.py`: the tasks' tests.
- `backend/tests/engine/replay/dewpoint-0.1.0+abi8/`: the recorded histories.

Changed:
- `backend/src/dewpoint/core/models/runs.py`: `RunStep.effect_preview`.
- `backend/src/dewpoint/core/runs/service.py`: the precedence, `StepConflict`.
- `backend/src/dewpoint/apps/worker/store.py`: the conflict's log line.
- `backend/src/dewpoint/apps/worker/activities.py`: a simulated attempt's failures.
- `backend/src/dewpoint/engine/__init__.py`: `ENGINE_ABI = 8`.
- `backend/src/dewpoint/engine/runtime/scheduler.py`: `take_ends`, `start_target`.
- `backend/src/dewpoint/engine/runtime/execution.py`: end rows, effects, simulated attempts and timers, the seeded
  view, lazy ends.
- `backend/src/dewpoint/engine/runtime/activities.py`: `StepRow.effect_preview`, `RunInput.target_step_id`.
- `backend/src/dewpoint/engine/runtime/workflow.py`: a single-step run's guards and completion.
- `backend/src/dewpoint/engine/cel/bind.py`: `ScopeView.framed`.
- `backend/src/dewpoint/engine/runtime/resolve.py`: `item` read when framed; a variable read through a claimed
  `vars`.
- `backend/tests/support/plugins/testkit.py`: `testkit.slow_simulator`.
- `backend/tests/apps/worker/harness.py`: the in-memory store's precedence.
- Existing tests whose rows B4b changes: `test_run_graph.py`, `test_run_graph_continue.py`,
  `test_run_graph_handles.py`, `test_run_graph_servicenow.py`.
- `backend/tests/core/test_migration_chain.py`, `backend/tests/core/runs/test_service.py`,
  `backend/tests/engine/runtime/test_scheduler.py`, `test_scheduler_properties.py`,
  `backend/tests/apps/worker/test_activities.py`, `test_run_graph_policies.py`,
  `backend/tests/engine/cel/test_profile.py`, `backend/tests/engine/replay/scenarios.py`.
- `docs/superpowers/specs/2026-09-25-engine-core-design.md` §8, `docs/operations/runs.md`.
- `docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md` §3.6 and §5.2 (rulings 3 and 13, once
  accepted).
- `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`.

## Milestones

1. **B4b** (Tasks 1–5): the ledger, migration 0071, the upsert precedence, the scheduler's ends, the end rows and
   `ENGINE_ABI` 8. **Pause:** the owner's review. Every run's rows change here.
2. **Simulation** (Tasks 6–7): simulated attempts and flow timers.
3. **S2 and the close** (Tasks 8–11): the seed contract, single-step runs, lazy end rows, every check and the final
   checkpoint. **Pause:** a fresh reviewer, the summary; then stop.

## How to run things

Every command runs from the plan's worktree. `$WT` is that worktree's root. Each command is written out whole: none
is kept in a shell variable, which zsh wouldn't split into words.

- **Python.** From `$WT/backend`, the worktree's own environment is made from the lock: `uv sync --frozen` installs
  exactly `uv.lock` into `$WT/backend/.venv`. It installs packages, so the owner's OK is asked at the start. The test
  suite's own setup (`uv run alembic upgrade head`) would make the same environment. Then:
  ```bash
  uv run --frozen python -c 'import dewpoint; print(dewpoint.__file__)'   # must print $WT/backend/src/...
  ```
- **Tests.** The database tests start PostgreSQL in Docker (testcontainers); Docker must be reachable. Use six
  workers: twelve overloaded Docker in the check (connections closed during a migration). From `$WT/backend`:
  `uv run --frozen pytest -q -p no:cacheprovider -n 6 <files>`.
- **A diff.** Copy the block, between its fences, to a file in the plan's workspace. Then, from `$WT`:
  `git apply --check <file> && git apply <file>`. Expected: no output. A diff that doesn't apply means the tree
  differs from what the previous task left: stop and compare, never apply by hand.
- **The golden histories.** From `$WT/backend`: `uv run --frozen python -m tests.engine.replay.record`. It records the
  scenarios the build's directory lacks, and names them.
- **Static checks.** From `$WT/backend`: `uv run --frozen ruff check src tests`, `uv run --frozen ruff format --check
  src tests`, `uv run --frozen mypy src`, `uv run --frozen lint-imports`. Expected: "All checks passed!", "… files
  already formatted", "Success: no issues found in … source files", "Contracts: 11 kept, 0 broken."
- **The whole backend suite** (`-n auto`) takes about the CI job's 12 minutes, so the owner is asked before it runs.
  It runs at the end only; each task runs its own tests.
- **Local CodeQL**, at the end: `scratchpad/codeql/scan.sh <sha>` (about 40 s).

## Executing this plan

- **Inline**, by one implementing agent in one session, with the owner's reviews at the milestone pauses, and a fresh
  independent review at the end. Test-first, as each task's steps say. The owner chooses.
- **The branch** is settled with the owner at the start. The default proposed: `feat/editor-4d1a` from `origin/main`,
  in its own worktree (`~/4_dev/mist_dewpoint-4d1a`), with the docs branch `docs/editor-ui-4d1-spec` (the spec and
  this plan) merged into it first. A later main is merged in, never rebased.
- **Where the code base differs from a step**, the executor stops at the diff that doesn't apply, adapts it test-first
  and records the difference as a mid-slice ruling in the ledger (M90 onward).
- **The rulings above** join the ledger only when the owner accepts the plan; until then the ledger says they're
  proposed.

---

# Milestone 1 — B4b

### Task 1: The ledger: the owner's 4d-1 rulings, the slots, and this plan proposed

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (the "Migration slots" table; append at the end)
- Modify: `docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md` (§3.6 and §5.2, as far as the owner
  accepts rulings 2, 3, 13 and 16)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger sections later tasks append to (`### 4d-1a, milestone N`).

- [ ] **Step 1: The slots**

In the "Migration slots" table, replace the rows for 0048–0065 and 0071 with:

```markdown
| 0048–0065 | 2b-4b's work (#90, merged 2026-10-12, chained 0044 → 0047 → 0045 → 0070 → 0048 → … → 0065). B4b and B8, reserved at 0048 and 0049 on 2026-10-08, moved to 0071 and 0072 (the owner, 2026-10-11) |
| 0071 | B4b: `skipped` and `not_started` projection statuses and `run_steps.effect_preview` (the owner, 2026-10-08; the slot, 2026-10-11); 4d-1a, chained after 0065 |
```

- [ ] **Step 2: Append the owner's rulings and the plan's status**

Append exactly:

```markdown
### Owner, 4d-1 design, mockups and spec (2026-10-12 and 2026-10-13, in chat)

4d-1 is Simulate workflow and Simulate step (outline §2 4d, D14). The owner chose, one decision at a time:
- three plans: 4d-1a (the engine: B4b, simulated attempts and timers, S2's engine part; ABI 8; 0071), 4d-1b (B8:
  draft snapshots, admission, readers; 0072), 4d-1c (the UI);
- B4b's statuses `skipped` and `not_started`, and S2, a single step from supplied values (seeds), engine-run.

Through the question prompt, the owner accepted:
- section 1 (B4b), with D-a1–D-a7, the upsert precedence and 0071's refusing downgrade;
- capacity (b): no draft cap; flow timers aren't waited in any simulate run of an ABI-8 version;
- section 2a (B8), and section 2b (S2's engine contract), which closed D-a8;
- section 3 (the UI) as the mockups' direction.

D8: pasted reviews held the "4d-1 Simulation Mockups" canvas at versions 16 and 19. The owner signed off version 20
(16 boards, light and dark, two true 320 px boards). The spec,
`docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md`, was approved by the owner and committed on
`docs/editor-ui-4d1-spec` (99fda408, 2026-10-13).

### 4d-1a plan (2026-10-13)

`docs/superpowers/plans/2026-10-13-editor-ui-4d1a-engine.md`, revision 7. Its rulings (1–16) are proposed, and join
this ledger as 159 onward only when the owner accepts the plan. Rulings 2 (its value rules), 3, 13 and 16 change the
spec's §5.2 and §3.6.
```

- [ ] **Step 3: The spec, where rulings 2, 3, 13 and 16 change it**

Each change only once the owner has accepted its ruling, in their own words. For ruling 13, in
`docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md`, §3.6, replace:

```markdown
- If 0071 lags a new build, rejected rows are dropped with a log (`apps/worker/store.py`): the deploy order is migration
  first, as for every ABI bump.
```

with:

```markdown
- If 0071 lags a new build, its projections fail on the missing column and are retried until the migration lands:
  nothing is dropped, and runs' ends wait for it. The deploy order is migration first, as for every ABI bump.
```

For ruling 3, in §5.2, after the "Overlaps" item, insert:

```markdown
- **Lists and every step's results:** a read through a list index is a read of the whole list (a seed never builds a
  list with gaps). A CEL value that reads `steps` or `loops` without naming a step's section reads every step's
  results, so its step can't be simulated alone.
```

For ruling 2, in §5.2, after the "Nothing outside the contract" item, insert:

```markdown
- **A value given:** checked against its entry's schema for types and value rules (enum, pattern, bounds, closed
  objects); inside it, presence and null follow the uses, never what the schema's `required` obliges (`required`
  inside `not` or `if` still tests the value).
```

For ruling 16, in §5.2, after the "Evaluation contexts" item, insert:

```markdown
- **A filter over a computed list:** what its predicate reads strictly of each element can't be traced to a seed, so
  the values its items are computed from keep their schema's `required` there. A guarded or defaulted predicate read
  keeps nothing.
```

A ruling not accepted leaves its part of the spec as it is, and is reported as open in Task 11. If ruling 2's value
rules are dropped, the executor stops at Task 8: a check of types alone needs its own plan (ruling 2). If ruling 16 is
dropped, the executor stops at Task 8 too: a filter over a computed list then needs another way to keep what its
predicate reads, or to refuse the target, and its own plan. Turning the check off would take elements the predicate
fails on.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md \
  docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md
git commit -m "docs(editor-4): the owner's 4d-1 rulings, the slots, and the 4d-1a plan proposed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Migration 0071: the wider status check and `run_steps.effect_preview`

**Spec:** §3.2, §3.5, §3.6.

**Files:**
- Create: `backend/migrations/versions/0071_step_instance_ends.py`
- Create: `backend/tests/migrations/test_0071.py`
- Modify: `backend/src/dewpoint/core/models/runs.py` (`RunStep.effect_preview`)
- Modify: `backend/src/dewpoint/engine/runtime/activities.py` (`StepRow.status`'s comment, `StepRow.effect_preview`)
- Modify: `backend/src/dewpoint/engine/runtime/execution.py` (`effect_preview` made storable with the previews)
- Modify: `backend/tests/core/test_migration_chain.py`

**Interfaces:**
- Consumes: `migrations.online` (`online`, `step`, `plain`, `exists`); `tests.migrations.support` (`copy`,
  `upgrade`, `downgrade`); `tests.migrations.test_0053` (`_drop`, `_sql`); `tests.probes.migration_locks.seed`.
- Produces: `run_steps.status` in `running | succeeded | failed | cancelled | skipped | not_started`;
  `run_steps.effect_preview` (JSONB, null); `RunStep.effect_preview`; `StepRow.effect_preview: Any = None`.

The column comes in a step of its own (no rewrite). The wider check is added `NOT VALID`, validated outside any
transaction (it reads every row without blocking writes), then put in the old one's place. Each step is skipped when
it's done already, so an interrupted upgrade goes on from where it stopped. The downgrade takes a share lock, refuses
while a row records either new status or an effect, then restores the old check and drops the column.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/core/test_migration_chain.py b/backend/tests/core/test_migration_chain.py
--- a/backend/tests/core/test_migration_chain.py
+++ b/backend/tests/core/test_migration_chain.py
@@ -24,7 +24,7 @@ def script() -> ScriptDirectory:
 
 
 def test_the_chain_has_one_head() -> None:
-    assert script().get_heads() == ["0065"]
+    assert script().get_heads() == ["0071"]
 
 
 def test_runs_workflow_last_comes_after_the_orphan_backoff() -> None:
@@ -45,3 +45,8 @@ def test_the_endpoint_sender_comes_after_the_samples_record() -> None:
 def test_2b_4bs_migrations_come_after_the_endpoint_sender() -> None:
     """2b-4b's first, 0048, was written on 0044 and chained, when it met main, after main's head then, 0070."""
     assert script().get_revision("0048").down_revision == "0070"
+
+
+def test_the_step_instance_ends_come_after_2b_4bs_last() -> None:
+    """Slot 0071 (4d-1a, B4b) is chained after main's head when it was written, 0065 (2b-4b's last)."""
+    assert script().get_revision("0071").down_revision == "0065"
diff --git a/backend/tests/migrations/test_0071.py b/backend/tests/migrations/test_0071.py
new file mode 100644
--- /dev/null
+++ b/backend/tests/migrations/test_0071.py
@@ -0,0 +1,95 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Migration 0071 on disposable databases, in a cluster of this module's own (editor 4d-1a, B4b): `run_steps` takes
+`skipped` and `not_started` and an `effect_preview`; an upgrade interrupted between its steps goes on from there; its
+downgrade refuses while a row records either status or an effect."""
+
+import asyncio
+from collections.abc import AsyncIterator, Iterator
+
+import asyncpg
+import pytest
+from testcontainers.community.postgres import PostgresContainer
+
+from tests.migrations.support import copy, downgrade, upgrade
+from tests.migrations.test_0053 import _drop, _sql
+from tests.probes.migration_locks import seed
+
+ROOTS = 5
+STEP = ("INSERT INTO run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, effect_preview) "
+        "SELECT tenant_id, id, gen_random_uuid(), '', 1, 'k', $1, $2::jsonb FROM runs LIMIT 1")  # fmt: skip
+
+
+async def _rows(url: str, query: str, *args: object) -> list[tuple[object, ...]]:
+    c = await asyncpg.connect(url)
+    try:
+        return [tuple(r) for r in await c.fetch(query, *args)]
+    finally:
+        await c.close()
+
+
+async def _step(url: str, status: str, effect: str | None = None) -> None:
+    c = await asyncpg.connect(url)
+    try:
+        await c.execute(STEP, status, effect)
+    finally:
+        await c.close()
+
+
+@pytest.fixture(scope="module")
+def cluster() -> Iterator[str]:
+    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
+        yield pg.get_connection_url().rsplit("/", 1)[0]
+
+
+@pytest.fixture(scope="module")
+def template(cluster: str) -> str:
+    """A seeded database at 0065, as the deployments that run 0071 are."""
+    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "t0065"'))
+    upgrade(f"{cluster}/t0065", "0034")
+    asyncio.run(seed(f"{cluster}/t0065", ROOTS))
+    upgrade(f"{cluster}/t0065", "0065")
+    return "t0065"
+
+
+@pytest.fixture
+async def db(cluster: str, template: str) -> AsyncIterator[str]:
+    url = await copy(cluster, template)
+    yield url
+    await _drop(cluster, url.rsplit("/", 1)[1])
+
+
+async def test_run_steps_take_the_new_statuses_and_an_effect(db: str) -> None:
+    await asyncio.to_thread(upgrade, db, "0071")
+    await _step(db, "skipped")
+    await _step(db, "not_started")
+    await _step(db, "succeeded", '{"port": "true"}')
+    with pytest.raises(asyncpg.CheckViolationError):
+        await _step(db, "unknown")
+    names = await _rows(db, "SELECT conname FROM pg_constraint WHERE conname LIKE 'run_steps_status%'")
+    assert names == [("run_steps_status",)]  # the wider check took the old one's name
+
+
+async def test_an_upgrade_interrupted_after_the_wider_check_goes_on(db: str) -> None:
+    await _sql(db, "ALTER TABLE run_steps ADD COLUMN effect_preview jsonb",
+               "ALTER TABLE run_steps ADD CONSTRAINT run_steps_status_0071 CHECK (status IN ('running', 'succeeded', "
+               "'failed', 'cancelled', 'skipped', 'not_started')) NOT VALID")  # fmt: skip
+    await asyncio.to_thread(upgrade, db, "0071")
+    names = await _rows(db, "SELECT conname, convalidated FROM pg_constraint WHERE conname LIKE 'run_steps_status%'")
+    assert names == [("run_steps_status", True)]
+    await _step(db, "not_started")
+
+
+async def test_the_downgrade_refuses_while_a_row_records_a_new_status_or_an_effect(db: str) -> None:
+    await asyncio.to_thread(upgrade, db, "0071")
+    for status, effect in (("skipped", None), ("succeeded", '{"port": "false"}')):
+        await _step(db, status, effect)
+        with pytest.raises(Exception, match="0071 refused"):
+            await asyncio.to_thread(downgrade, db, "0065")
+        await _sql(db, "DELETE FROM run_steps WHERE status = 'skipped' OR effect_preview IS NOT NULL")
+    await asyncio.to_thread(downgrade, db, "0065")
+    columns = await _rows(db, "SELECT 1 FROM information_schema.columns WHERE table_name = 'run_steps' "
+                              "AND column_name = 'effect_preview'")  # fmt: skip
+    assert columns == []
+    with pytest.raises(asyncpg.CheckViolationError):  # the old check is back
+        await _sql(db, "INSERT INTO run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status) "
+                       "SELECT tenant_id, id, gen_random_uuid(), '', 1, 'k', 'skipped' FROM runs LIMIT 1")  # fmt: skip
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/migrations/test_0071.py
tests/core/test_migration_chain.py tests/core/test_model_schema.py tests/qualification/test_reference_rights.py`

Expected: FAIL, 5 failed and 6 passed: the chain's head is `['0065']`, not `['0071']`; 0071's tests and its chaining
test can't find revision `0071` ("Can't locate revision identified by '0071'", "No such revision or branch '0071'").

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/migrations/versions/0071_step_instance_ends.py b/backend/migrations/versions/0071_step_instance_ends.py
new file mode 100644
--- /dev/null
+++ b/backend/migrations/versions/0071_step_instance_ends.py
@@ -0,0 +1,59 @@
+# SPDX-License-Identifier: Apache-2.0
+"""B4b (editor 4d-1a; the simulation design §3): every step instance's end is recorded.
+
+- `run_steps.status` gains `skipped` (a branch not taken) and `not_started` (an instance discarded before it began: a
+  scope's failure, a stop or fail step, a cancel, the deadline; or a retry that never began).
+- `run_steps.effect_preview`: what a control step did besides its output, protected like `output_preview`: the port an
+  `if` or a `switch` took (`{"port": …}`), the variables a `set_variables` assigned (`{"assignments": …}`).
+
+Online (2b-4b, D15): the column is added in a step of its own (no rewrite); the wider check is added `NOT VALID` in
+another, validated outside any transaction (it reads every row without blocking writes), then put in the old one's
+place. The roles' table grants on `run_steps` cover the new column. Its downgrade refuses while a row records either
+new status or an effect: dropping them would lose what ABI-8 runs recorded (stop the ABI-8 workers first)."""
+
+import sqlalchemy as sa
+from alembic import op
+from sqlalchemy.dialects.postgresql import JSONB
+
+from migrations.online import exists, online, plain, step
+
+revision = "0071"
+down_revision = "0065"
+branch_labels = None
+depends_on = None
+
+STATUSES = "('running', 'succeeded', 'failed', 'cancelled', 'skipped', 'not_started')"
+WIDER = "run_steps_status_0071"
+WIDENED = ("SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'run_steps_status' "
+           "AND pg_get_constraintdef(oid) LIKE '%not_started%')")  # fmt: skip
+LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
+REFUSE_DOWNGRADE = """DO $$ BEGIN
+  IF EXISTS (SELECT 1 FROM run_steps WHERE status IN ('skipped', 'not_started') OR effect_preview IS NOT NULL) THEN
+    RAISE EXCEPTION '0071 refused: a step row records skipped, not_started or an effect';
+  END IF;
+END $$"""
+
+
+def upgrade() -> None:
+    with online() as conn:
+        step(conn, "0071 run_steps.effect_preview",
+             lambda: op.add_column("run_steps", sa.Column("effect_preview", JSONB())),
+             done=exists("column", "effect_preview", "run_steps"))  # fmt: skip
+        step(conn, "0071 run_steps_status, wider",
+             f"ALTER TABLE run_steps ADD CONSTRAINT {WIDER} CHECK (status IN {STATUSES}) NOT VALID",
+             done=f"SELECT ({WIDENED}) OR ({exists('constraint', WIDER)})")  # fmt: skip
+        plain(conn, "0071 run_steps_status validated", f"ALTER TABLE run_steps VALIDATE CONSTRAINT {WIDER}",
+              done=WIDENED)  # fmt: skip
+        step(conn, "0071 run_steps_status, swapped", "ALTER TABLE run_steps DROP CONSTRAINT run_steps_status",
+             f"ALTER TABLE run_steps RENAME CONSTRAINT {WIDER} TO run_steps_status", done=WIDENED)  # fmt: skip
+
+
+def downgrade() -> None:
+    for statement in (LOCK_TIMEOUT, "LOCK TABLE run_steps IN SHARE MODE", REFUSE_DOWNGRADE):
+        op.execute(statement)
+    op.execute("ALTER TABLE run_steps DROP CONSTRAINT run_steps_status")
+    op.execute(
+        "ALTER TABLE run_steps ADD CONSTRAINT run_steps_status "
+        "CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled'))"
+    )
+    op.drop_column("run_steps", "effect_preview")
diff --git a/backend/src/dewpoint/core/models/runs.py b/backend/src/dewpoint/core/models/runs.py
--- a/backend/src/dewpoint/core/models/runs.py
+++ b/backend/src/dewpoint/core/models/runs.py
@@ -95,6 +95,7 @@ class RunStep(Base):
     error_message: Mapped[str | None] = mapped_column(Text)
     outcome: Mapped[str | None] = mapped_column(String(16))
     cel_mode: Mapped[str | None] = mapped_column(String(16))
+    effect_preview: Mapped[Any] = mapped_column(JSONB)  # a control step's port or assignments (0071)
 
 
 class RunStepConnection(Base):
diff --git a/backend/src/dewpoint/engine/runtime/activities.py b/backend/src/dewpoint/engine/runtime/activities.py
--- a/backend/src/dewpoint/engine/runtime/activities.py
+++ b/backend/src/dewpoint/engine/runtime/activities.py
@@ -291,7 +291,7 @@ class StepRow:
     node_key: str
     iteration_key: str
     attempt: int
-    status: str  # running | succeeded | failed | cancelled
+    status: str  # running | succeeded | failed | cancelled | skipped | not_started
     started_at: str | None = None
     ended_at: str | None = None
     input_preview: Any = None
@@ -300,6 +300,7 @@ class StepRow:
     error_message: str | None = None
     outcome: str | None = None
     cel_mode: str | None = None
+    effect_preview: Any = None  # a control step's effect besides its output: {"port"} or {"assignments"}
 
 
 @dataclass(frozen=True)
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -684,6 +684,7 @@ class Execution:
             row,
             input_preview=storable(row.input_preview),
             output_preview=storable(row.output_preview),
+            effect_preview=storable(row.effect_preview),
             error_code=sanitize(row.error_code),
             error_message=sanitize(row.error_message),
         )
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 11 passed. The privilege reference's test passes with the reference
unchanged (ruling 9).

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/0071_step_instance_ends.py backend/tests/migrations/test_0071.py \
  backend/src/dewpoint/core/models/runs.py backend/src/dewpoint/engine/runtime/activities.py \
  backend/src/dewpoint/engine/runtime/execution.py backend/tests/core/test_migration_chain.py
git commit -m "feat(runs): migration 0071, step-instance ends and a control step's effect (B4b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: A known step result is never replaced

**Spec:** §3.4.

**Files:**
- Modify: `backend/src/dewpoint/core/runs/service.py` (`StepConflict`, `_provisional`, `upsert_steps`)
- Modify: `backend/src/dewpoint/apps/worker/store.py` (`_conflicted`, at both upsert sites)
- Modify: `backend/tests/apps/worker/harness.py` (`MemoryStore._upsert`, `MemoryStore.conflicts`)
- Modify: `backend/tests/core/runs/test_service.py`
- Create: `backend/tests/apps/worker/test_store_precedence.py`

**Interfaces:**
- Consumes: Task 2's `effect_preview`; `OUTCOME_UNCONFIRMED` (`core.runs.service`).
- Produces: `upsert_steps(s, tenant_id, rows) -> list[StepConflict]`; `StepConflict(run_id, step_id, iteration_key,
  attempt, kept, refused)`; the log line `step_result_conflict` (ids and statuses only); `MemoryStore.conflicts`.

The precedence, by the stored row and the incoming one:
- a `running` row takes anything, and its first `started_at` stands;
- a provisional close (`failed`, `outcome_unconfirmed`) gives way only to a genuine end;
- a genuine end is never replaced: the same end again changes nothing, and a different one is refused, returned and
  logged.

It also fixes an ordering bug the spec names. `apps/worker/store._late()` turns a late `running` row of an ended run
into a provisional close, which the old upsert wrote over a genuine result.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/worker/harness.py b/backend/tests/apps/worker/harness.py
--- a/backend/tests/apps/worker/harness.py
+++ b/backend/tests/apps/worker/harness.py
@@ -77,6 +77,10 @@ class HeldClaim:
     kind: str
 
 
+def _provisional(row: StepRow) -> bool:
+    return row.status == "failed" and row.error_code == OUTCOME_UNCONFIRMED
+
+
 def unconfirmed(row: StepRow) -> StepRow:
     """A step whose outcome no one recorded, as the stores close it (2b-4b M2)."""
     return dataclasses.replace(row, status="failed", error_code=OUTCOME_UNCONFIRMED, error_message=UNCONFIRMED_MESSAGE,
@@ -97,6 +101,7 @@ class MemoryStore:
     grants: set[tuple[str, str]] = field(default_factory=set)  # (claim, run) (2b spec §3.4)
     index_of: dict[str, set[str]] = field(default_factory=dict)  # root run -> its secret index (2b spec §3.7)
     versions_of: dict[str, int] = field(default_factory=dict)  # root run -> its index's version
+    conflicts: list[tuple[tuple[str, str, str, int], str, str]] = field(default_factory=list)  # §3.4 refusals
 
     def add(self, g: G, workflow_id: uuid.UUID | None = None, *, engine_abi: int = ENGINE_ABI) -> str:
         """Publish `g` as a version, pinned to the sub-flows it runs (as `publish` registered them). `engine_abi`:
@@ -153,7 +158,7 @@ class MemoryStore:
             if row.status == "running" and (row.run_id in self.runs or any(in_batch(row.iteration_key, b)
                                                                             for b in closed)):  # fmt: skip
                 row = unconfirmed(row)
-            self.rows[(row.run_id, row.step_id, row.iteration_key, row.attempt)] = row
+            self._upsert(row)
         if data.run is not None and not (data.run.if_running and data.run.run_id in self.runs):
             self.runs[data.run.run_id] = data.run
         if data.run is not None:
@@ -171,6 +176,25 @@ class MemoryStore:
             if key[0] == run_id and row.status == "running" and inside:
                 self.rows[key] = unconfirmed(row)
 
+    def _upsert(self, row: StepRow) -> None:
+        """As `upsert_steps` writes it (the simulation design §3.4): `running` takes anything, keeping its first start;
+        a provisional close gives way only to a genuine final row; a genuine final row is never replaced, and a
+        different one is recorded in `conflicts`."""
+        key = (row.run_id, row.step_id, row.iteration_key, row.attempt)
+        stored = self.rows.get(key)
+        if stored is None or stored.status == "running":
+            started = stored.started_at if stored is not None and stored.started_at else row.started_at
+            self.rows[key] = dataclasses.replace(row, started_at=started)
+            return
+        genuine = row.status != "running" and not _provisional(row)
+        if _provisional(stored):
+            if genuine:
+                self.rows[key] = dataclasses.replace(row, started_at=stored.started_at or row.started_at)
+            return
+        compared = ("status", "outcome", "error_code", "error_message", "output_preview", "effect_preview")
+        if genuine and any(getattr(stored, k) != getattr(row, k) for k in compared):
+            self.conflicts.append((key, stored.status, row.status))
+
     def steps(self, run_id: str) -> list[StepRow]:
         return [r for k, r in sorted(self.rows.items()) if k[0] == run_id]
 
diff --git a/backend/tests/apps/worker/test_store_precedence.py b/backend/tests/apps/worker/test_store_precedence.py
new file mode 100644
--- /dev/null
+++ b/backend/tests/apps/worker/test_store_precedence.py
@@ -0,0 +1,61 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The worker's store under the upsert precedence (the simulation design §3.4): a step's row projected late, after its
+run ended, lands provisional and never replaces the genuine result there before it; a different genuine result for the
+same attempt is refused, and logged by ids and statuses only."""
+
+import uuid
+from typing import Any
+
+import structlog
+from sqlalchemy import text
+
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.engine.runtime.activities import ProjectInput, StepRow
+from tests.apps.test_admission import KEYS
+from tests.core.runs.test_service import seeded_run, steps
+
+STEP = str(uuid.UUID(int=7))
+
+
+def step(run_id: uuid.UUID, status: str, **extra: Any) -> StepRow:
+    return StepRow(str(run_id), STEP, "a", "", 1, status, **extra)
+
+
+async def test_a_running_row_projected_after_its_runs_end_never_replaces_its_result(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    """`_late()` closes a `running` row of an ended run as `outcome_unconfirmed`: that close used to replace the genuine
+    result projected before it."""
+    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    store = DbRunStore(worker_sessionmaker, KEYS)
+    done = step(run_id, "succeeded", output_preview={"v": 1}, outcome="applied")
+    await store.project(ProjectInput(str(tenant), [done]))
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update runs set status = 'succeeded', ended_at = now() where id = :i"), {"i": run_id})
+    await store.project(ProjectInput(str(tenant), [step(run_id, "running")]))
+    [only] = await steps(owner_sessionmaker, tenant, run_id)
+    assert (only.status, only.output_preview, only.error_code) == ("succeeded", {"v": 1}, None)
+
+
+async def test_a_different_result_for_the_same_attempt_is_logged_by_ids_and_statuses(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    store = DbRunStore(worker_sessionmaker, KEYS)
+    await store.project(ProjectInput(str(tenant), [step(run_id, "succeeded", output_preview={"v": 1})]))
+    other = step(run_id, "failed", error_code="boom", error_message="a message, never logged")
+    with structlog.testing.capture_logs() as seen:
+        await store.project(ProjectInput(str(tenant), [other]))
+    [event] = [e for e in seen if e["event"] == "step_result_conflict"]
+    assert event == {
+        "event": "step_result_conflict",
+        "log_level": "warning",
+        "run_id": str(run_id),
+        "step_id": STEP,
+        "iteration_key": "",
+        "attempt": 1,
+        "kept": "succeeded",
+        "refused": "failed",
+    }
+    [only] = await steps(owner_sessionmaker, tenant, run_id)
+    assert (only.status, only.output_preview) == ("succeeded", {"v": 1})
diff --git a/backend/tests/core/runs/test_service.py b/backend/tests/core/runs/test_service.py
--- a/backend/tests/core/runs/test_service.py
+++ b/backend/tests/core/runs/test_service.py
@@ -57,6 +57,66 @@ async def test_upserts_are_idempotent_and_a_late_running_row_never_wins(
     assert (only.status, only.output_preview, only.outcome) == ("succeeded", {"v": 1}, "applied")
 
 
+async def upsert(worker: Any, tenant: uuid.UUID, rows: list[dict[str, Any]]) -> list[Any]:
+    async with worker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        return await service.upsert_steps(s, tenant, rows)
+
+
+def provisional(run_id: uuid.UUID) -> dict[str, Any]:
+    return row(run_id, "failed", error_code=service.OUTCOME_UNCONFIRMED, error_message=service.UNCONFIRMED_MESSAGE)
+
+
+async def test_a_genuine_result_replaces_a_provisional_close_and_the_first_start_stands(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    """The simulation design §3.4: `running` takes anything, keeping its first `started_at`; a provisional close
+    (`outcome_unconfirmed`) gives way to the genuine result that arrives after it."""
+    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    first, later = datetime(2026, 10, 13, 9, 0, tzinfo=UTC), datetime(2026, 10, 13, 9, 5, tzinfo=UTC)
+    done = row(run_id, "succeeded", output_preview={"v": 1}, outcome="applied")
+    for rows in ([row(run_id, "running", started_at=first)], [row(run_id, "running", started_at=later)],
+                 [provisional(run_id)], [done]):  # fmt: skip
+        assert await upsert(worker_sessionmaker, tenant, rows) == []
+    [only] = await steps(owner_sessionmaker, tenant, run_id)
+    assert (only.status, only.output_preview, only.started_at) == ("succeeded", {"v": 1}, first)
+
+
+async def test_a_late_close_or_running_row_never_replaces_a_genuine_result(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    """Both arrival orders: the genuine result first, then a provisional close and a late `running` row (what
+    `_late()` makes of one) change nothing, and the same result again is no conflict."""
+    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    done = row(run_id, "succeeded", output_preview={"v": 1}, outcome="applied")
+    for rows in ([done], [provisional(run_id)], [row(run_id, "running")], [done]):
+        assert await upsert(worker_sessionmaker, tenant, rows) == []
+    [only] = await steps(owner_sessionmaker, tenant, run_id)
+    assert (only.status, only.output_preview, only.error_code) == ("succeeded", {"v": 1}, None)
+
+
+async def test_a_different_genuine_result_is_refused_and_returned(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    assert await upsert(worker_sessionmaker, tenant, [row(run_id, "succeeded", output_preview={"v": 1})]) == []
+    other = row(run_id, "failed", error_code="boom", error_message="x")
+    [conflict] = await upsert(worker_sessionmaker, tenant, [other])
+    assert (conflict.run_id, conflict.attempt, conflict.kept, conflict.refused) == (run_id, 1, "succeeded", "failed")
+    [only] = await steps(owner_sessionmaker, tenant, run_id)
+    assert (only.status, only.output_preview) == ("succeeded", {"v": 1})
+
+
+async def test_an_effect_is_stored_as_storage_writes_it(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    effect = {"assignments": {"note": "a\x00b", "n": float("nan")}}
+    await upsert(worker_sessionmaker, tenant, [row(run_id, "succeeded", effect_preview=effect)])
+    [only] = await steps(owner_sessionmaker, tenant, run_id)
+    assert only.effect_preview == {"assignments": {"note": "a\ufffdb", "n": "nan"}}
+
+
 async def test_messages_are_sanitized(owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker) -> None:
     tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
     async with worker_sessionmaker() as s, s.begin():
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/core/runs/test_service.py
tests/apps/worker/test_store_precedence.py tests/apps/worker/test_run_graph.py`

Expected: FAIL, 6 failed and 29 passed:
- `upsert_steps` returns `None` where a list is expected;
- the effect isn't stored;
- the late close replaced the genuine result: `('failed', None, 'outcome_unconfirmed')` where `('succeeded', {'v':
  1}, None)` was expected, the bug the spec names;
- no `step_result_conflict` line is logged.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/worker/store.py b/backend/src/dewpoint/apps/worker/store.py
--- a/backend/src/dewpoint/apps/worker/store.py
+++ b/backend/src/dewpoint/apps/worker/store.py
@@ -71,6 +71,21 @@ def _row(row: StepRow) -> dict[str, Any]:
     }
 
 
+def _conflicted(conflicts: list[runs.StepConflict]) -> None:
+    """A genuine final row refused for another of its attempt's (the simulation design §3.4): the first stands. Ids
+    and statuses only."""
+    for c in conflicts:
+        _log.warning(
+            "step_result_conflict",
+            run_id=str(c.run_id),
+            step_id=str(c.step_id),
+            iteration_key=c.iteration_key,
+            attempt=c.attempt,
+            kept=c.kept,
+            refused=c.refused,
+        )
+
+
 class DbRunStore:
     def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource | None = None) -> None:
         """`keys`: the tenants' data keys, which claims and secret indexes are sealed with (engine 2b spec §3.1,
@@ -236,7 +251,7 @@ class DbRunStore:
                 async with s.begin_nested():
                     if data.start is not None:
                         await _start(s, tenant, data.start)
-                    await runs.upsert_steps(s, tenant, [_row(r) for r in data.steps])
+                    _conflicted(await runs.upsert_steps(s, tenant, [_row(r) for r in data.steps]))
                     if data.run is not None:
                         await _finish(s, data.run)
                         await _release(s, data.run)
@@ -270,7 +285,7 @@ class DbRunStore:
         for row in data.steps:
             try:
                 async with s.begin_nested():
-                    await runs.upsert_steps(s, tenant, [_row(row)])
+                    _conflicted(await runs.upsert_steps(s, tenant, [_row(row)]))
             except DBAPIError as e:
                 state = _refused(e)
                 if state is None:
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -1,7 +1,7 @@
 # SPDX-License-Identifier: Apache-2.0
 """Storage for runs and their per-step projection (engine spec §8). Rows arrive as plain mappings: `core` knows
-nothing of the engine. Every write is idempotent, so a retried projection changes nothing twice, and a late
-`running` row never overwrites a finished attempt."""
+nothing of the engine. Every write is idempotent, so a retried projection changes nothing twice, and a known
+outcome is never replaced (`upsert_steps`)."""
 
 import math
 import re
@@ -33,6 +33,7 @@ STEP_FIELDS = (
     "error_message",
     "outcome",
     "cel_mode",
+    "effect_preview",
 )
 
 
@@ -259,7 +260,32 @@ async def close_unconfirmed(s: AsyncSession, run_id: uuid.UUID, *, scopes: Seque
     await s.execute(query.values(**closed, ended_at=func.now()).execution_options(synchronize_session=False))
 
 
-async def upsert_steps(s: AsyncSession, tenant_id: uuid.UUID, rows: Iterable[Mapping[str, Any]]) -> None:
+@dataclass(frozen=True)
+class StepConflict:
+    """A genuine final row that met a different genuine final row of its attempt: the first was kept."""
+
+    run_id: uuid.UUID
+    step_id: uuid.UUID
+    iteration_key: str
+    attempt: int
+    kept: str  # the stored row's status
+    refused: str  # the incoming row's
+
+
+_COMPARED = ("status", "outcome", "error_code", "error_message", "output_preview", "effect_preview")
+
+
+def _provisional(status: Any, error_code: Any) -> Any:
+    """A row closed `outcome_unconfirmed` (a reconciler's or a late projection's close): terminal, not a known end."""
+    return (status == "failed") & (error_code == OUTCOME_UNCONFIRMED)
+
+
+async def upsert_steps(s: AsyncSession, tenant_id: uuid.UUID, rows: Iterable[Mapping[str, Any]]) -> list[StepConflict]:
+    """Each row by the precedence of the simulation design §3.4: a `running` row takes anything, keeping its first
+    `started_at`; a provisional close (`outcome_unconfirmed`) gives way only to a genuine final row; a genuine final
+    row is never replaced. The same final row again changes nothing; a different genuine final row is refused and
+    returned, for the caller to report."""
+    conflicts: list[StepConflict] = []
     for row in rows:
         values = {
             "tenant_id": tenant_id,
@@ -273,15 +299,47 @@ async def upsert_steps(s: AsyncSession, tenant_id: uuid.UUID, rows: Iterable[Map
         values["error_message"] = sanitize(values["error_message"])
         values["input_preview"] = storable(values["input_preview"])
         values["output_preview"] = storable(values["output_preview"])
+        values["effect_preview"] = storable(values["effect_preview"])
         statement = insert(RunStep).values(**values)
         fresh = statement.excluded
-        await s.execute(
+        set_ = {k: getattr(fresh, k) for k in STEP_FIELDS}
+        set_["started_at"] = func.coalesce(RunStep.started_at, fresh.started_at)  # the first start stands
+        genuine = (fresh.status != "running") & ~_provisional(fresh.status, fresh.error_code)
+        written = await s.execute(
             statement.on_conflict_do_update(
                 index_elements=["run_id", "step_id", "iteration_key", "attempt"],
-                set_={k: getattr(fresh, k) for k in STEP_FIELDS},
-                where=(RunStep.status == "running") | (fresh.status != "running"),
-            )
+                set_=set_,
+                where=(RunStep.status == "running") | (_provisional(RunStep.status, RunStep.error_code) & genuine),
+            ).returning(RunStep.run_id)
         )
+        incoming_genuine = values["status"] != "running" and not (
+            values["status"] == "failed" and values["error_code"] == OUTCOME_UNCONFIRMED
+        )
+        if written.first() is not None or not incoming_genuine:
+            continue
+        stored = (
+            await s.execute(
+                select(*(getattr(RunStep, k) for k in _COMPARED)).where(
+                    RunStep.run_id == values["run_id"],
+                    RunStep.step_id == values["step_id"],
+                    RunStep.iteration_key == values["iteration_key"],
+                    RunStep.attempt == values["attempt"],
+                )
+            )
+        ).one()
+        provisional = stored.status == "failed" and stored.error_code == OUTCOME_UNCONFIRMED
+        if not provisional and tuple(stored) != tuple(values[k] for k in _COMPARED):
+            conflicts.append(
+                StepConflict(
+                    values["run_id"],
+                    values["step_id"],
+                    values["iteration_key"],
+                    values["attempt"],
+                    stored.status,
+                    values["status"],
+                )
+            )
+    return conflicts
 
 
 async def get_run(s: AsyncSession, run_id: uuid.UUID) -> Run | None:
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 35 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/core/runs/service.py backend/src/dewpoint/apps/worker/store.py \
  backend/tests/apps/worker/harness.py backend/tests/core/runs/test_service.py \
  backend/tests/apps/worker/test_store_precedence.py
git commit -m "fix(runs): a known step result is never replaced; a different one is refused and logged (B4b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The scheduler says how each instance ended without settling

**Spec:** §3.1, §3.2.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/scheduler.py`
- Modify: `backend/tests/engine/runtime/test_scheduler.py`
- Modify: `backend/tests/engine/runtime/test_scheduler_properties.py`

**Interfaces:**
- Consumes: the scheduler's `_check_ready`, `_fail_scope` and `end`.
- Produces: `SKIPPED, UNSTARTED, STOPPED = "skipped", "unstarted", "stopped"`;
  `Scheduler.take_ends() -> list[tuple[Instance, str]]`, in the order the instances ended.

Each instance of each opened scope ends exactly once: it settles (`take_settled`), or it ends otherwise:
- **skipped**, on a branch not taken: `_check_ready` marks it dead;
- **unstarted**, waiting or queued when its scope failed or the run ended;
- **stopped**, handed out then. It's cancelled too; the workflow knows whether it began.

An iteration never opened has no instances. A snapshot is never taken with ends not yet taken. The property test
gains the invariant over random runs: every instance a scope opened is settled or ended exactly once. Its runs under a
small open-iteration cap or live-state budget reach deferred work too (spec §8's "deferred").

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/engine/runtime/test_scheduler.py b/backend/tests/engine/runtime/test_scheduler.py
--- a/backend/tests/engine/runtime/test_scheduler.py
+++ b/backend/tests/engine/runtime/test_scheduler.py
@@ -283,3 +283,47 @@ def test_a_stop_ends_the_run_and_cancels_running_work() -> None:
     s.succeed(a, {})
     s.end(RunEnd("succeeded", stopped=True))
     assert [name(s, i) for i in s.take_cancels()] == ["b"]
+
+
+# --- how instances end without settling (B4b, the simulation design §3) -------------------------------------------
+
+
+def ends(s: Scheduler) -> set[tuple[str, str]]:
+    return {(name(s, i), kind) for i, kind in s.take_ends()}
+
+
+def test_a_branch_not_taken_ends_skipped_with_what_only_it_leads_to() -> None:
+    g = G().node("c", IF, {"condition": True}).node("a", ECHO).node("b", ECHO).node("only_b", ECHO).node("j", ECHO)
+    g.edge("c", "a", "true").edge("c", "b", "false").edge("b", "only_b").edge("a", "j").edge("b", "j")
+    s = started(g)
+    [c] = s.take_ready()
+    s.succeed(c, {}, ("true",))
+    assert ends(s) == {("b", "skipped"), ("only_b", "skipped")}
+    assert run_all(s) == ["a", "j"]
+    assert ends(s) == set()  # each instance ends once
+
+
+def test_a_scope_failure_ends_handed_work_stopped_and_waiting_work_unstarted() -> None:
+    s = started(G().node("a", ECHO).node("b", ECHO).node("c", ECHO).edge("b", "c"))
+    a, _ = s.take_ready()
+    s.fail(a, BOOM)
+    assert ends(s) == {("b", "stopped"), ("c", "unstarted")}
+    assert [name(s, i) for i in s.take_cancels()] == ["b"]  # stopped work is cancelled too
+
+
+def test_the_runs_end_ends_queued_work_unstarted() -> None:
+    s = started(G().node("a", ECHO).node("b", ECHO).node("c", ECHO).edge("a", "c"))
+    [a] = s.take_ready(limit=1)  # `b` stays queued: never handed out
+    s.end(RunEnd("deadline_exceeded", Failure("deadline_exceeded", "The run passed its deadline.")))
+    assert ends(s) == {("a", "stopped"), ("b", "unstarted"), ("c", "unstarted")}
+    assert [name(s, i) for i in s.take_cancels()] == [name(s, a)]
+
+
+def test_a_stopped_loop_ends_its_open_iterations_and_an_item_never_opened_has_no_instances() -> None:
+    s = started(loop_graph())
+    [loop] = s.take_ready()
+    s.open_loop(loop, [1, 2, 3], concurrency=2, stop_on_error=True)
+    x0, _ = s.take_ready()
+    s.fail(x0, BOOM)
+    assert ends(s) == {("l:0/y", "unstarted"), ("l:1/x", "stopped"), ("l:1/y", "unstarted"), ("after", "unstarted")}
+    assert s.ended == RunEnd("failed", BOOM)
diff --git a/backend/tests/engine/runtime/test_scheduler_properties.py b/backend/tests/engine/runtime/test_scheduler_properties.py
--- a/backend/tests/engine/runtime/test_scheduler_properties.py
+++ b/backend/tests/engine/runtime/test_scheduler_properties.py
@@ -1,6 +1,7 @@
 # SPDX-License-Identifier: Apache-2.0
 """Spec §10, on random graphs with if/switch/joins/error ports/loops, completed in random orders:
-- every node runs or dies exactly once per scope;
+- every node runs or dies exactly once per scope, and every instance of every opened scope is reported exactly once:
+  settled, or ended (skipped, unstarted or stopped: B4b);
 - dead paths never run;
 - a step runs in its own region's scope, so branches that reconverge meet in the same scope;
 - no edge is left pending when a run succeeds, so nothing deadlocks.
@@ -123,15 +124,30 @@ def run(g: G, data: st.DataObject) -> None:
     collects: list[Any] = []
     batches: list[Batch] = []
     handed: dict[Instance, int] = {}
+    reported: dict[Instance, int] = {}
+    seen: set[Instance] = set()
+
+    def drain() -> None:
+        for inst, _ in s.take_settled():
+            reported[inst] = reported.get(inst, 0) + 1
+        for inst, kind in s.take_ends():
+            reported[inst] = reported.get(inst, 0) + 1
+            if kind == S.STOPPED:
+                assert inst in handed, "a step never handed out was reported stopped"
+            else:
+                assert inst not in handed, f"a step handed out was reported {kind}"
+        seen.update(Instance(k, n) for k, sc in s.scopes.items() if not sc.frozen for n in sc.nodes)
+
     while s.ended is None:
         assert s.open_scopes <= s.cap + s.reserve, "open iteration scopes passed the cap and the reservation"
         assert s.live == s.recount(), "the live-state counter drifted from what the state holds"
         cancelled = set(s.take_cancels())
         running = [r for r in running if r not in cancelled]
+        drain()
         batches = [b for b in batches if b.loop not in cancelled]
         # continue-as-new: carry on from a snapshot, taken with work still queued, as drain mode leaves it
         if data.draw(st.integers(0, 7), label="snapshot") == 0 and s.live <= S.LIVE_BUDGET:
-            s.take_settled()
+            drain()
             s = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json(check=True))), prefix="t:1:run:2")
         for inst in s.take_ready():
             handed[inst] = handed.get(inst, 0) + 1
@@ -187,6 +203,10 @@ def run(g: G, data: st.DataObject) -> None:
             s.fail(inst, Failure("testkit.boom", "it broke"))
         else:
             s.succeed(inst, {"n": "x" * data.draw(st.sampled_from([0, 50, 400, 700]), label="output")})
+    s.take_cancels()
+    drain()
+    assert all(n == 1 for n in reported.values()), "an instance was reported twice"
+    assert all(reported.get(i) == 1 for i in seen), "an instance of an opened scope was never reported"
     # dead steps never ran; every step of a scope that finished normally settled, with no edge left pending
     for scope in s.scopes.values():
         for node_id, state in scope.nodes.items():
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/engine/runtime`

Expected: FAIL, 5 failed and 222 passed: "'Scheduler' object has no attribute 'take_ends'" (four unit tests and the
property test).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/scheduler.py b/backend/src/dewpoint/engine/runtime/scheduler.py
--- a/backend/src/dewpoint/engine/runtime/scheduler.py
+++ b/backend/src/dewpoint/engine/runtime/scheduler.py
@@ -45,7 +45,12 @@ child writes its segments where its parent's loop names them, and returns its co
 
 A snapshot (`snapshot_format` 2, engine 2b spec §5.3) holds states, not queues: one code per node and per edge in
 region order, steps and loops by their topological index. Restoring rebuilds what's queued from those states, minus
-what was handed out before the snapshot and is still running."""
+what was handed out before the snapshot and is still running.
+
+Every instance of every opened scope ends exactly once (B4b, the simulation design §3): it settles (`take_settled`),
+or it ends otherwise (`take_ends`): `skipped`, on a branch not taken; `unstarted`, waiting or queued when its scope
+failed or the run ended; `stopped`, handed out then, so cancelled too (the workflow knows whether it began). An
+iteration never opened has no instances."""
 
 import bisect
 import heapq
@@ -63,6 +68,7 @@ from dewpoint.engine.runtime.program import BODY, DONE, ERROR_PORT, Program, Ste
 from dewpoint.engine.runtime.size import inline_limit
 
 ScopeKey = tuple[tuple[str, int], ...]
+SKIPPED, UNSTARTED, STOPPED = "skipped", "unstarted", "stopped"  # how an instance ended without settling (B4b)
 ITERATION_CAP = 100_000  # loop iterations and filter items across the whole logical run (spec §4.2)
 ITERATION_CAP_EXCEEDED = "iteration_cap_exceeded"
 CAP_MESSAGE = "This run reached its limit of 100,000 loop iterations."
@@ -531,6 +537,7 @@ class Scheduler:
         self._batches: list[Batch] = []
         self._cancels: list[Instance] = []
         self._settled: list[tuple[Instance, dict[str, Any]]] = []
+        self._ends: list[tuple[Instance, str]] = []  # instances that ended without settling, and how (B4b)
         self._budget_waits: dict[str, Instance] = {}  # a need's key -> the loop waiting for it
         self._topo_of_key = {s.key: s.topo for s in program.steps.values()}
         self._members: dict[uuid.UUID | None, tuple[uuid.UUID, ...]] = {
@@ -668,6 +675,12 @@ class Scheduler:
         out, self._cancels = sorted(self._cancels, key=self.order), []
         return out
 
+    def take_ends(self) -> list[tuple[Instance, str]]:
+        """Instances that ended without settling since the last call (B4b): SKIPPED, UNSTARTED or STOPPED, in the
+        order they ended."""
+        out, self._ends = self._ends, []
+        return out
+
     def take_spills(self) -> list[Spill]:
         """Containers' parts to claim, as units: they only shrink the state, so a drain still starts them."""
         out, self._spills = self._spills, []
@@ -892,8 +905,12 @@ class Scheduler:
         queued = set(self._ready) | self._deferred
         for scope in self.scopes.values():
             for node_id, state in scope.nodes.items():
-                if state == NodeState.RUNNING and Instance(scope.key, node_id) not in queued:
-                    self._cancels.append(Instance(scope.key, node_id))
+                inst = Instance(scope.key, node_id)
+                if state == NodeState.RUNNING and inst not in queued:
+                    self._cancels.append(inst)
+                    self._ends.append((inst, STOPPED))
+                elif state in (NodeState.RUNNING, NodeState.WAITING):
+                    self._ends.append((inst, UNSTARTED))
         self._ready = []
         self._clear_deferred(())
         self._starting.clear()
@@ -1034,6 +1051,7 @@ class Scheduler:
                 self._vrefs[self.vars_version] = self._vrefs.get(self.vars_version, 0) + 1
             return None
         scope.nodes[node_id] = NodeState.DEAD
+        self._ends.append((Instance(scope.key, node_id), SKIPPED))
         return step
 
     def _fail_scope(self, scope: Scope, failure: Failure, *, report: bool = True) -> None:
@@ -1051,6 +1069,9 @@ class Scheduler:
                 if state == NodeState.RUNNING and inst not in queued and inst not in self._deferred:
                     self._cancels.append(inst)
                     self._handed.discard(inst)
+                    self._ends.append((inst, STOPPED))
+                elif state in (NodeState.RUNNING, NodeState.WAITING):
+                    self._ends.append((inst, UNSTARTED))
                 if state in (NodeState.RUNNING, NodeState.WAITING):
                     inner.nodes[node_id] = NodeState.DEAD
         self._ready = [r for r in self._ready if r.scope[: len(scope.key)] != scope.key]
@@ -1634,7 +1655,7 @@ class Scheduler:
         """`to_json` in parts: after each, it yields the structural units it took (codes and captures encoded), so
         the execution can spread a large snapshot over workflow tasks. Nothing changes the state between parts: a
         snapshot is taken only when nothing runs."""
-        if self._settled or self._cancels or self.ended is not None:
+        if self._settled or self._cancels or self._ends or self.ended is not None:
             raise ValueError("a snapshot is taken only between units, and never after the run ended")
         if self.budget.waiting or self.budget.reserved or self._budget_waits:  # the at-continue term (§5.3)
             raise ValueError("a snapshot is taken only when the iteration budget holds no waiting need or child grant")
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 227 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/engine/runtime/scheduler.py backend/tests/engine/runtime/test_scheduler.py \
  backend/tests/engine/runtime/test_scheduler_properties.py
git commit -m "feat(engine): the scheduler reports how each instance ended without settling (B4b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Every step instance's end is projected, at `ENGINE_ABI` 8

**Spec:** §3.1–§3.5, §8.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/execution.py`
- Modify: `backend/src/dewpoint/engine/__init__.py` (`ENGINE_ABI = 8`, its history)
- Modify: `docs/superpowers/specs/2026-09-25-engine-core-design.md` (§8's `run_steps`)
- Create: `backend/tests/apps/worker/test_run_graph_ends.py`
- Modify: `backend/tests/apps/worker/test_run_graph.py`, `test_run_graph_continue.py`, `test_run_graph_handles.py`,
  `test_run_graph_servicenow.py` (the rows B4b adds)
- Modify: `backend/tests/engine/cel/test_profile.py` (the ABI tripwire)
- Record: `backend/tests/engine/replay/dewpoint-0.1.0+abi8/` (with the commit)

**Interfaces:**
- Consumes: Task 4's `take_ends` and its kinds (as `live_state.SKIPPED` …); Task 2's `StepRow.effect_preview`.
- Produces: `Execution._row(inst, status, **fields) -> StepRow`; `Execution._queue_end(inst, kind, now)`;
  `Execution._effect_of(effect) -> dict | None`; `Execution._queue_late(inst, effect)`; the sets `_attempted` and
  `_finished`, and the map `_effects`; the snapshot's `loops`; `ENGINE_ABI = 8`.

How each end is rowed:
- **Ends the scheduler reports.** `skipped` and `not_started` record attempt 1, with no start. A stopped instance is
  `cancelled` once it began (in `_started`), and `not_started` if it never did.
- **A plugin step that reached an attempt** (`_attempted`) rows each of its ends itself. A retry stopped in its
  backoff is `not_started` at the attempt it waited for (D-a1).
- **A control step** queues a `running` row when it starts; a step that waits on nothing replaces it before it's sent
  (D-a2). One that finished in the activation that ended its run or scope keeps its real outcome (`_finished`,
  `_queue_late`; D-a3).
- **Effects.** An `if`'s or a `switch`'s port and a `set_variables`'s assignments go in `effect_preview`.
- **Across a continue-as-new.** The snapshot carries each open loop's start and CEL mode, as it does a sleeping
  timer's, so a loop still open in the continued execution ends `cancelled`, never `not_started` (ruling 15).

The commands change, so `ENGINE_ABI` becomes 8 and this task records the abi8 histories.

Two of the spec's cases are pinned by tests that exist already:
- a timer carried across continue-as-new resumes, and is never rowed `cancelled`.
  `test_draining_settles_what_is_outstanding_and_a_timer_keeps_its_wake_time` keeps one row for it, spanning its
  hour: a `cancelled` row first would stand under Task 3's precedence;
- the same rows projected twice change nothing: Task 3's tests, and
  `test_upserts_are_idempotent_and_a_late_running_row_never_wins`.

D-a3's two orders are the new tests for a control step that finished as the run ended (its outcome kept) and one the
end reached first (`test_a_stop_cancels_a_sleeping_timer_that_said_it_was_running`: `cancelled`).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/worker/test_run_graph.py b/backend/tests/apps/worker/test_run_graph.py
--- a/backend/tests/apps/worker/test_run_graph.py
+++ b/backend/tests/apps/worker/test_run_graph.py
@@ -53,7 +53,9 @@ async def test_a_cel_branch_runs_one_side_and_projects_control_steps(env: Workfl
     assert (result.status, result.outputs) == ("succeeded", {"side": "yes"})
     rows = {r.node_key: r for r in store.steps(run_id_of(handle))}
     assert rows["c"].status == "succeeded" and rows["c"].cel_mode == "local"  # this build runs its profile in-process
-    assert "no" not in rows and store.runs[run_id_of(handle)].status == "succeeded"
+    assert rows["c"].effect_preview == {"port": "true"}  # the branch it took (0071)
+    assert (rows["no"].status, rows["no"].started_at) == ("skipped", None)  # the branch not taken (B4b)
+    assert store.runs[run_id_of(handle)].status == "succeeded"
 
 
 async def test_a_loop_collects_per_item_and_a_filter_keeps_matches(env: WorkflowEnvironment) -> None:
diff --git a/backend/tests/apps/worker/test_run_graph_continue.py b/backend/tests/apps/worker/test_run_graph_continue.py
--- a/backend/tests/apps/worker/test_run_graph_continue.py
+++ b/backend/tests/apps/worker/test_run_graph_continue.py
@@ -111,7 +111,8 @@ async def test_a_cancel_while_the_run_gets_ready_to_continue_as_new_ends_it_canc
             await asyncio.wait_for(handle.result(), 30)
         runs = await chain(env.client, handle.id, handle.first_execution_run_id or "")
     assert len(runs) == 1 and store.runs[run_id_of(handle)].status == "cancelled"
-    assert [(r.node_key, r.status) for r in store.steps(run_id_of(handle))] == [("a", "succeeded")]  # `b` never started
+    rows = sorted((r.node_key, r.status) for r in store.steps(run_id_of(handle)))
+    assert rows == [("a", "succeeded"), ("b", "not_started")]  # `b` never started (B4b)
 
 
 @dataclasses.dataclass
@@ -161,7 +162,8 @@ async def test_a_cancel_while_the_run_settles_for_continue_as_new_lets_its_proje
         history = await first.fetch_history()
     requested = [e for e in history.events if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_CANCEL_REQUESTED]
     assert requested == [] and store.runs[run_id_of(handle)].status == "cancelled"
-    assert sorted(r.node_key for r in store.steps(run_id_of(handle))) == ["a", "c"]  # `b` never started
+    rows = sorted((r.node_key, r.status) for r in store.steps(run_id_of(handle)))
+    assert rows == [("a", "succeeded"), ("b", "not_started"), ("c", "succeeded")]  # `b` never started (B4b)
 
 
 def doubler() -> G:
@@ -239,7 +241,8 @@ async def test_the_headroom_draining_adds_is_measured_and_bounded(own_env: Workf
     assert result.status == "succeeded", result.error
     assert len(runs) >= 2, "it never drained"
     drained = (await snapshot(runs[0]))["drained"]
-    assert drained["units"] == {"activities": 90, "children": 10}  # the cap was saturated when draining began
+    units = {k: n for k, n in drained["units"].items() if k != "project"}  # the loops' `running` rows may be in flight
+    assert units == {"activities": 90, "children": 10}  # the cap was saturated when draining began
     (began, continued), (size_began, size_continued) = drained["events"], drained["bytes"]
     during = [e for e in runs[0].events if began < e.event_id <= continued]
     retried = [
diff --git a/backend/tests/apps/worker/test_run_graph_ends.py b/backend/tests/apps/worker/test_run_graph_ends.py
new file mode 100644
--- /dev/null
+++ b/backend/tests/apps/worker/test_run_graph_ends.py
@@ -0,0 +1,208 @@
+# SPDX-License-Identifier: Apache-2.0
+"""B4b (the simulation design §3): every instance of every opened scope ends with a row. A branch not taken is
+`skipped`; work discarded before it began is `not_started`, with no start; work stopped once it began is `cancelled`;
+a retry stopped in its backoff is `not_started` at the attempt it waited for; a control step that waits on something
+says `running` first; a control step that finished as its run ended keeps its outcome; an `if`'s port and a
+`set_variables`'s assignments are its `effect_preview`."""
+
+import asyncio
+import dataclasses
+from typing import Any
+
+import pytest
+from temporalio.client import WorkflowFailureError
+from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.engine.runtime.activities import ProjectInput
+from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run_id_of, start, workers
+from tests.support.graphs import G, cel
+from tests.support.plugins.testkit import Slow
+
+ECHO, SLOW, FAIL_N = "testkit.echo@1", "testkit.slow@1", "testkit.fail_n@1"
+IF, LOOP, SET, DELAY, STOP = "flow.if@1", "flow.loop@1", "flow.set_variables@1", "flow.delay@1", "flow.stop@1"
+FAIL = "flow.fail@1"
+
+
+def graph() -> G:
+    g = G()
+    g.settings = {"input_schema": {"type": "object"}}
+    return g
+
+
+def ended(store: MemoryStore, run_id: str) -> dict[tuple[str, str, int], tuple[str, bool]]:
+    """Each row's (status, whether it has a start), by (step, iteration, attempt)."""
+    return {(r.node_key, r.iteration_key, r.attempt): (r.status, r.started_at is not None) for r in store.steps(run_id)}
+
+
+@dataclasses.dataclass
+class Seen(MemoryStore):
+    """Every (step, status) a projection carried, in order: what a run said while it ran."""
+
+    seen: list[tuple[str, str]] = dataclasses.field(default_factory=list)
+    said: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
+
+    async def project(self, data: ProjectInput) -> None:
+        self.seen += [(r.node_key, r.status) for r in data.steps]
+        if ("d", "running") in self.seen:
+            self.said.set()
+        await super().project(data)
+
+
+async def test_the_deadline_cancels_running_work_and_ends_waiting_work_not_started(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("a", SLOW, {"seconds": 60}).node("b", ECHO, {"value": 1}).edge("a", "b")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {}, max_run_duration_s=5)
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert result.status == "deadline_exceeded"
+    assert ended(store, run_id_of(handle)) == {("a", "", 1): ("cancelled", True), ("b", "", 1): ("not_started", False)}
+
+
+async def test_a_retry_stopped_in_its_backoff_is_not_started_at_the_attempt_it_waited_for(
+    env: WorkflowEnvironment,
+) -> None:
+    """D-a1: attempt 1 keeps its failure; attempt 2 never began (the backoff is 1 s, the deadline half of it)."""
+    store = MemoryStore()
+    g = graph().node("f", FAIL_N, {"failures": 1})
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {}, max_run_duration_s=0.5)
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert result.status == "deadline_exceeded"
+    rows = {r.attempt: r for r in store.steps(run_id_of(handle))}
+    assert (rows[1].status, rows[1].error_code) == ("failed", "testkit.transient")
+    assert (rows[2].status, rows[2].started_at, rows[2].input_preview) == ("not_started", None, None)
+
+
+async def test_a_stop_cancels_a_sleeping_timer_that_said_it_was_running(env: WorkflowEnvironment) -> None:
+    """D-a2: a control step that waits on something says `running` first; stopped, it's `cancelled` with its start."""
+    store = Seen()
+    g = graph().node("d", DELAY, {"duration_s": 3600}).node("s", SLOW, {"seconds": 1}).node("stop", STOP)
+    g.edge("s", "stop")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {})
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert result.status == "succeeded"  # a stop ends the run as succeeded
+    assert ("d", "running") in store.seen
+    assert ended(store, run_id_of(handle))[("d", "", 1)] == ("cancelled", True)
+
+
+async def test_a_failed_iteration_ends_its_own_steps_and_leaves_the_other_iterations(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("l", LOOP, {"items": [0, 1]}, on_error="continue")
+    g.nodes[0]["config"]["on_item_error"] = "continue"
+    g.node("x", IF, {"condition": cel("item == 0")}).node("f", FAIL_N, {"failures": 10}).node("e", ECHO, {"value": 1})
+    g.node("after_f", ECHO, {"value": 2})
+    g.edge("l", "x", "body").edge("x", "f", "true").edge("x", "e", "false").edge("f", "after_f")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {})
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert result.status == "succeeded"
+    rows = ended(store, run_id_of(handle))
+    finals = {(k, it): rows[(k, it, max(a for kk, ii, a in rows if (kk, ii) == (k, it)))][0] for k, it, _ in rows}
+    assert finals == {
+        ("l", ""): "succeeded",
+        ("x", "l:0"): "succeeded", ("f", "l:0"): "failed", ("e", "l:0"): "skipped", ("after_f", "l:0"): "not_started",
+        ("x", "l:1"): "succeeded", ("f", "l:1"): "skipped", ("e", "l:1"): "succeeded", ("after_f", "l:1"): "skipped",
+    }  # fmt: skip
+
+
+async def test_the_port_an_if_took_and_what_set_variables_assigned_are_recorded(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph()
+    g.settings["vars_schema"] = {"type": "object", "properties": {"n": {"type": "integer", "default": 0}}}
+    g.node("v", SET, {"assignments": {"n": 3}}).node("c", IF, {"condition": cel("vars.n > 2")})
+    g.node("yes", ECHO, {"value": 1}).edge("v", "c").edge("c", "yes", "true")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {})
+        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}
+    assert rows["v"].effect_preview == {"assignments": {"n": 3}}
+    assert rows["c"].effect_preview == {"port": "true"}
+    assert rows["yes"].effect_preview is None
+
+
+async def test_a_control_step_that_finished_as_the_run_ended_keeps_its_outcome(env: WorkflowEnvironment) -> None:
+    """D-a3: `stop` and `v` start together and finish in the same activation; `stop` is applied first and ends the
+    run, and `v`'s outcome, known by then, is its row."""
+    store = MemoryStore()
+    g = graph()
+    g.settings["vars_schema"] = {"type": "object", "properties": {"n": {"type": "integer", "default": 0}}}
+    g.node("stop", STOP).node("v", SET, {"assignments": {"n": 1}})
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {})
+        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    rows: dict[str, Any] = {r.node_key: r for r in store.steps(run_id_of(handle))}
+    assert (rows["stop"].status, rows["v"].status) == ("succeeded", "succeeded")
+    assert rows["v"].effect_preview == {"assignments": {"n": 1}}
+
+
+async def test_a_cancel_ends_started_work_cancelled_and_queued_work_not_started(env: WorkflowEnvironment) -> None:
+    """101 steps ready at once: the in-flight cap starts 100 and queues one. A cancel stops the 100 that began
+    (`cancelled`, with their start); the one queued never began (`not_started`, no start). About 30 s: a cancel reaches
+    a running activity with its next heartbeat the SDK sends, and no step sets a heartbeat timeout."""
+    store = MemoryStore()
+    g = graph()
+    for n in range(101):
+        g.node(f"s{n}", SLOW, {"seconds": 120})
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {})
+        run_id = run_id_of(handle)
+        for _ in range(600):  # until the cap's 100 have begun: each beats once a second
+            if sum(1 for run, _ in Slow.beats if run == run_id) >= 100:
+                break
+            await asyncio.sleep(0.05)
+        await handle.cancel()
+        with pytest.raises(WorkflowFailureError):
+            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert store.runs[run_id].status == "cancelled"
+    rows = ended(store, run_id)
+    assert sorted(rows.values()).count(("cancelled", True)) == 100
+    assert [v for v in rows.values() if v != ("cancelled", True)] == [("not_started", False)]
+
+
+async def test_a_loop_open_across_a_continue_as_new_ends_cancelled_with_its_first_start(
+    env: WorkflowEnvironment,
+) -> None:
+    """A loop whose iterations still sleep when the run continues as new began in the first execution: a cancel in
+    the continued one ends it `cancelled`, with the start the first one recorded, never `not_started`."""
+    from tests.apps.worker.test_run_graph_continue import chain
+
+    store = MemoryStore()
+    g = graph()
+    g.node("l", LOOP, {"items": list(range(10)), "concurrency": 10}).node("d", DELAY, {"duration_s": 3600})
+    g.edge("l", "d", "body")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {}, drain_events=15)
+        for _ in range(200):
+            if len(await chain(env.client, handle.id, handle.first_execution_run_id or "")) >= 2:
+                break
+            await asyncio.sleep(0.05)
+        else:
+            raise AssertionError("it never continued as new")
+        first = [r.started_at for r in store.steps(run_id_of(handle)) if r.node_key == "l"]
+        await handle.cancel()
+        with pytest.raises(WorkflowFailureError):
+            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    [loop] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "l"]
+    assert (loop.status, loop.started_at) == ("cancelled", first[0])
+    assert {r.status for r in store.steps(run_id_of(handle)) if r.node_key == "d"} == {"cancelled"}
+
+
+async def test_inside_a_batch_every_opened_iteration_ends_each_of_its_steps(env: WorkflowEnvironment) -> None:
+    """A loop of 150 items runs its iterations in batches (child runs), which row their ends as the run does: item
+    130's `if` takes `true` and fails the run; the branch it didn't take is `skipped`; every step of every iteration
+    that opened has its final row, and no iteration that never opened has any."""
+    store = MemoryStore()
+    g = graph()
+    g.node("l", LOOP, {"items": list(range(150))})
+    g.node("i", IF, {"condition": cel("item == 130")}).node("f", FAIL, {"message": "item 130"}).node("e", ECHO)
+    g.edge("l", "i", "body").edge("i", "f", "true").edge("i", "e", "false")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {})
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert (result.status, result.error["code"]) == ("failed", "workflow_failed")
+    rows = ended(store, run_id_of(handle))
+    assert rows[("e", "l:130", 1)] == ("skipped", False) and rows[("f", "l:130", 1)][0] == "failed"
+    opened = {key for (_, key, _) in rows if key.startswith("l:")}
+    assert "l:130" in opened and all({n for (n, k, _) in rows if k == key} == {"i", "f", "e"} for key in opened)
+    assert all(status != "running" for status, _ in rows.values())
diff --git a/backend/tests/apps/worker/test_run_graph_handles.py b/backend/tests/apps/worker/test_run_graph_handles.py
--- a/backend/tests/apps/worker/test_run_graph_handles.py
+++ b/backend/tests/apps/worker/test_run_graph_handles.py
@@ -145,7 +145,7 @@ async def test_a_declassified_condition_over_a_sensitive_value_decides_plainly(e
     async with workers(env.client, store):
         result = await run(env.client, store, g, TRIGGER, claimed=True)
     assert result.status == "succeeded", result.error
-    ran = {r.node_key for r in store.steps(result_run(store))}
+    ran = {r.node_key for r in store.steps(result_run(store)) if r.status != "skipped"}  # B4b rows the other side
     assert "a" in ran and "b" not in ran  # the branch taken: what the listed site reveals (spec §4.3)
 
 
@@ -180,7 +180,7 @@ async def test_a_reference_to_a_sensitive_value_decides_a_listed_branch_and_case
     async with workers(env.client, store):
         result = await run(env.client, store, g, {"vip": True, "tier": 1}, claimed=True)
     assert result.status == "succeeded", result.error
-    ran = {r.node_key for r in store.steps(result_run(store))}
+    ran = {r.node_key for r in store.steps(result_run(store)) if r.status != "skipped"}  # B4b rows the other side
     assert {"y", "d"} <= ran and not {"n", "g"} & ran
 
 
diff --git a/backend/tests/apps/worker/test_run_graph_servicenow.py b/backend/tests/apps/worker/test_run_graph_servicenow.py
--- a/backend/tests/apps/worker/test_run_graph_servicenow.py
+++ b/backend/tests/apps/worker/test_run_graph_servicenow.py
@@ -240,4 +240,5 @@ async def test_a_created_answer_too_deep_to_decode_creates_no_second_incident(
     async with worker_sessionmaker() as s, s.begin():
         await tenant_scope(s, ctx.tenant_id)
         rows = (await s.execute(text("select node_key, status, error_code from run_steps"))).all()
-    assert [tuple(r) for r in rows] == [("create", "failed", "servicenow.created_unreadable")]
+    ended_rows = [tuple(r) for r in rows if r[1] != "not_started"]  # the steps after it never started (B4b)
+    assert ended_rows == [("create", "failed", "servicenow.created_unreadable")]
diff --git a/backend/tests/engine/cel/test_profile.py b/backend/tests/engine/cel/test_profile.py
--- a/backend/tests/engine/cel/test_profile.py
+++ b/backend/tests/engine/cel/test_profile.py
@@ -13,4 +13,4 @@ def test_the_profile_names_the_installed_runtime() -> None:
 def test_local_evaluation_is_a_build_constant_tied_to_the_engine_abi() -> None:
     """Tripwire (spec §5.9 rollout): LOCAL_CEL_PROFILE is part of engine_abi. Changing it without bumping ENGINE_ABI
     would let an open run replay on a build that routes its CEL differently. Update both, then this pair."""
-    assert (ENGINE_ABI, profile.LOCAL_CEL_PROFILE) == (7, profile.CURRENT_CEL_PROFILE)
+    assert (ENGINE_ABI, profile.LOCAL_CEL_PROFILE) == (8, profile.CURRENT_CEL_PROFILE)
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/worker/test_run_graph.py
tests/apps/worker/test_run_graph_continue.py tests/apps/worker/test_run_graph_handles.py
tests/apps/worker/test_run_graph_servicenow.py tests/apps/worker/test_run_graph_ends.py tests/engine/cel/test_profile.py
tests/engine/replay`

Expected: FAIL, 13 failed and 94 passed:
- the ABI tripwire (`test_local_evaluation_is_a_build_constant_tied_to_the_engine_abi`);
- every new end-row test, the cancel, the batch and the loop across a continue-as-new included;
- the existing tests now expecting `not_started`, `skipped` and control steps' rows.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/engine/__init__.py b/backend/src/dewpoint/engine/__init__.py
--- a/backend/src/dewpoint/engine/__init__.py
+++ b/backend/src/dewpoint/engine/__init__.py
@@ -10,5 +10,8 @@
 # the build's ABI. 6: 2b-1b's claims: a run's sensitive and large values held as handles, resolved in activities and
 # the evaluator; taint routing and declassified decisions; the exact workflow-id grammar. 7: 2b-4b's engine blockers:
 # binding charged the bytes measuring its views serialized (#18); a value several CEL binding sets share claimed once
-# and sent as its handle (#26); a step's CEL requests stopped before the run's history passes 32 MiB.
-ENGINE_ABI = 7
+# and sent as its handle (#26); a step's CEL requests stopped before the run's history passes 32 MiB. 8: editor 4d-1a
+# (the simulation design): every step instance's end projected (`skipped`, `not_started`, `cancelled`) with control
+# steps' `running` rows and effects; simulated attempts never of unknown outcome; flow timers not waited in a
+# simulation; single-step runs (`RunInput.target_step_id`).
+ENGINE_ABI = 8
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -289,6 +289,12 @@ class Execution:
         self._rows: dict[tuple[str, str, int], StepRow] = {}  # queued for the next projection, per attempt
         self._started: dict[Instance, str] = {}
         self._cel_modes: dict[Instance, str] = {}
+        # B4b: how each instance's end is rowed. A plugin step that reached an attempt rows every way it ends itself
+        # (`_attempted`); a unit whose task completed (`_finished`) has its real outcome, even when the run ended in
+        # the same activation; what a control step did besides its output waits for its row (`_effects`).
+        self._attempted: set[Instance] = set()
+        self._finished: set[Instance] = set()
+        self._effects: dict[Instance, dict[str, Any]] = {}
         self._projects = 0
         self._timers: dict[Instance, datetime] = {}  # a timer step asleep -> its wake time
         self._resume: list[Instance] = []  # timer steps a snapshot carried over: they re-arm first
@@ -450,6 +456,8 @@ class Execution:
                     if key[0] == "cancelled" and task.cancelled():
                         continue  # a unit we cancelled ended so: its cancel isn't this execution's
                     effect = task.result()
+                    if key[0] == "step" and effect is not None and effect.loop is None:
+                        self._finished.add(key[1])  # its outcome is known, whatever the run did meanwhile (D-a3)
                     if effect is not None and key[0] != "cancelled":
                         self._apply(key, effect)
         except GeneratorExit:
@@ -560,8 +568,12 @@ class Execution:
 
     async def _unit(self, key: tuple[Any, ...]) -> _Effect | None:
         if key[0] == "step":
-            self._started[key[1]] = workflow.now().isoformat()
-            return await self._step(key[1])
+            inst = key[1]
+            self._started[inst] = workflow.now().isoformat()
+            step = self.sched.step(inst)
+            if step.control:  # replaced by its end row before it's sent, unless it waits on something (D-a2)
+                self._queue(self._row(inst, "running", started_at=self._started[inst]))
+            return await self._step(inst)
         if key[0] == "batch":
             return await self._batch(self._batches.pop((key[1], key[2])))
         if key[0] == "spill":
@@ -602,6 +614,13 @@ class Execution:
         inst: Instance = key[1]
         if effect.cel_mode is not None:
             self._cel_modes[inst] = effect.cel_mode
+        if self.sched.step(inst).control and effect.loop is None:
+            done = self._effect_of(effect)
+            if done is not None:
+                self._effects[inst] = done
+            scope = self.sched.scopes.get(inst.scope)
+            if self.sched.ended is not None or scope is None or scope.failure is not None:
+                self._queue_late(inst, effect)  # finished as the run or its scope ended: its real outcome (D-a3)
         if effect.loop is not None:
             self.sched.open_loop(
                 inst,
@@ -710,7 +729,8 @@ class Execution:
         return preview(value, schema)
 
     def _queue_settled(self) -> None:
-        """Control steps that settled since the last call. Plugin steps queue their own attempts (`_activity`)."""
+        """Control steps that settled since the last call (plugin steps queue their own attempts, `_activity`), and
+        every instance that ended without settling (B4b): skipped, not started, or cancelled once it began."""
         now = workflow.now().isoformat()
         for inst, result in self.sched.take_settled():
             step = self.sched.step(inst)
@@ -718,21 +738,75 @@ class Execution:
                 continue
             error = result.get("error")
             self._queue(
-                StepRow(
-                    run_id=self.run_id,
-                    step_id=str(step.id),
-                    node_key=step.key,
-                    iteration_key=iteration_key(inst.scope),
-                    attempt=1,
-                    status="failed" if error else "succeeded",
+                self._row(
+                    inst,
+                    "failed" if error else "succeeded",
                     started_at=self._started.get(inst),
                     ended_at=now,
                     output_preview=self._preview(result.get("output")),
                     error_code=error["code"] if error else None,
                     error_message=error["message"] if error else None,
                     cel_mode=self._cel_modes.get(inst),
+                    effect_preview=self._effects.pop(inst, None),
                 )
             )
+        for inst, kind in self.sched.take_ends():
+            self._queue_end(inst, kind, now)
+
+    def _row(self, inst: Instance, status: str, **fields: Any) -> StepRow:
+        step = self.sched.step(inst)
+        return StepRow(
+            run_id=self.run_id,
+            step_id=str(step.id),
+            node_key=step.key,
+            iteration_key=iteration_key(inst.scope),
+            attempt=fields.pop("attempt", 1),
+            status=status,
+            **fields,
+        )
+
+    def _queue_end(self, inst: Instance, kind: str, now: str) -> None:
+        """An instance that ended without settling (B4b; the simulation design §3.3): `skipped` and `not_started`
+        record attempt 1 and no start. A stopped one was handed out: `cancelled` once it began (a control step, or a
+        plugin step still resolving its values), `not_started` if it never did. A plugin step that reached an attempt
+        rows its own end, and a unit that finished has its real outcome (D-a3)."""
+        step = self.sched.step(inst)
+        if kind == live_state.STOPPED:
+            if inst in self._finished or (not step.control and inst in self._attempted):
+                return
+            if inst in self._started:
+                self._queue(self._row(inst, "cancelled", started_at=self._started[inst], ended_at=now,
+                                      cel_mode=self._cel_modes.get(inst)))  # fmt: skip
+                return
+        status = "skipped" if kind == live_state.SKIPPED else "not_started"
+        self._queue(self._row(inst, status, ended_at=now))
+
+    @staticmethod
+    def _effect_of(effect: "_Effect") -> dict[str, Any] | None:
+        """What a control step did besides its output (0071's `effect_preview`): the port an `if` or a `switch` took,
+        the variables a `set_variables` assigned (handles where they're sensitive)."""
+        if effect.variables:
+            return {"assignments": preview(dict(effect.variables))}
+        if effect.ports is not None and len(effect.ports) == 1:
+            return {"port": effect.ports[0]}
+        return None
+
+    def _queue_late(self, inst: Instance, effect: "_Effect") -> None:
+        """A control step that finished as its run or scope ended (D-a3): its row records what it did."""
+        failure = effect.failure or (effect.end.failure if effect.end is not None else None)
+        self._queue(
+            self._row(
+                inst,
+                "failed" if failure is not None else "succeeded",
+                started_at=self._started.get(inst),
+                ended_at=workflow.now().isoformat(),
+                output_preview=None if failure is not None else self._preview(effect.output),
+                error_code=failure.code if failure is not None else None,
+                error_message=failure.message if failure is not None else None,
+                cel_mode=effect.cel_mode or self._cel_modes.get(inst),
+                effect_preview=self._effects.pop(inst, None),
+            )
+        )
 
     async def _close_batch(self, batch: UnconfirmedBatch) -> None:
         """A batch of this run's that a bug failed (the owner's ruling, 2b-4b M2): its rows still `running` close,
@@ -1698,6 +1772,7 @@ class Execution:
         timeout = timedelta(seconds=step.timeout_s or float(manifest["timeout_s"]))
         ambiguous = manifest["side_effect"] == AMBIGUOUS
         attempt = 1
+        self._attempted.add(inst)  # from here, each way it ends is rowed below
         while True:
             row = StepRow(
                 run_id=self.run_id,
@@ -1763,7 +1838,12 @@ class Execution:
                     failure, outcome, retryable = self._failed_attempt(e, row, step.key, ambiguous, retry)
                     if not retryable or attempt >= attempts:
                         return _Effect(failure=failure, cel_mode=cel_mode)
-                    await asyncio.sleep(_backoff(retry, attempt))  # a durable timer
+                    try:
+                        await asyncio.sleep(_backoff(retry, attempt))  # a durable timer
+                    except asyncio.CancelledError:  # stopped before the retry began: it never ran (D-a1)
+                        self._queue(replace(row, attempt=attempt + 1, status="not_started", started_at=None,
+                                            ended_at=workflow.now().isoformat(), input_preview=None))  # fmt: skip
+                        raise
                     attempt += 1
                     continue
                 # The run or the scope ended: the SDK reports our own cancel as an ActivityError. Never retry it.
@@ -1829,7 +1909,8 @@ class Execution:
 
     async def _snapshot(self) -> dict[str, Any]:
         """Where a continued run carries on (spec §6; `snapshot_format` 2, engine 2b spec §5.3). The projection is
-        written first, so no row is carried; timers carry their wake times."""
+        written first, so no row is carried; timers carry their wake times. Timers and open loops carry their start:
+        they began in an earlier execution, so one that ends now is `cancelled`, never `not_started` (B4b)."""
         return {
             "snapshot_format": SNAPSHOT_FORMAT,
             "scheduler": await self._stepwise(self.sched.encoding()),
@@ -1846,6 +1927,11 @@ class Execution:
                 ]
                 for i, wake in self._timers.items()
             ],
+            "loops": [
+                [[[k, n] for k, n in i.scope], str(i.step), self._started[i], self._cel_modes.get(i)]
+                for i in self.sched.loops
+                if i in self._started
+            ],
         }
 
     async def _restore(self, program: Program, snapshot: dict[str, Any]) -> None:
@@ -1862,6 +1948,11 @@ class Execution:
             if mode:
                 self._cel_modes[inst] = mode
             self._resume.append(inst)
+        for key, step, started, mode in snapshot["loops"]:
+            inst = Instance(tuple((str(k), int(n)) for k, n in key), uuid.UUID(step))
+            self._started[inst] = started
+            if mode:
+                self._cel_modes[inst] = mode
 
     async def _flush(self) -> None:
         """Before continuing as new: every queued row written, and every signal sent. A cancel that arrived meanwhile
diff --git a/docs/superpowers/specs/2026-09-25-engine-core-design.md b/docs/superpowers/specs/2026-09-25-engine-core-design.md
--- a/docs/superpowers/specs/2026-09-25-engine-core-design.md
+++ b/docs/superpowers/specs/2026-09-25-engine-core-design.md
@@ -1194,9 +1194,15 @@ cancel while the version loads cancels the run.
 - **`runs`:** id, tenant_id, workflow_version_id, kind (`run`, `subflow`, `failure_handler`), the parent run, step
   and iteration of a sub-run, status (`running`, `succeeded`, `failed`, `cancelled`,
   `deadline_exceeded`), started_at, ended_at, error summary.
-- **`run_steps`:** run_id, step_id, `iteration_key`, `attempt`, status, timestamps, redacted input and output
-  previews (≤ 8 KiB each), error code and sanitized message, `outcome` (`applied`, `simulated`, `outcome_unknown`),
-  and the CEL mode used (`local`, `activity`).
+- **`run_steps`:** run_id, step_id, `iteration_key`, `attempt`, status (`running`, `succeeded`, `failed`,
+  `cancelled`, `skipped`, `not_started`), timestamps, redacted input and output previews (≤ 8 KiB each), error code
+  and sanitized message, `outcome` (`applied`, `simulated`, `outcome_unknown`), the CEL mode used (`local`,
+  `activity`), and a control step's effect (`effect_preview`: an `if`'s or a `switch`'s port, a `set_variables`'s
+  assignments). Since engine ABI 8 (B4b; `2026-10-13-editor-4d1-simulation-design.md` §3), every instance of every
+  opened scope ends with a row: `skipped` on a branch not taken, `not_started` when it never began (a retry stopped in
+  its backoff records its next attempt so), `cancelled` once it began; a control step that waits on something says
+  `running` first. A row's genuine end is never replaced: a provisional close (`outcome_unconfirmed`) gives way to it,
+  and a different genuine end is refused and logged (`step_result_conflict`).
 - **Writes:**
   - A batched `project` activity upserts rows keyed `(run_id, step_id, iteration_key, attempt)`. It is the only
     writer: a plugin step's activity runs one attempt and writes nothing, and the workflow queues each attempt's
```

- [ ] **Step 4: Record the abi8 histories**

Run: `uv run --frozen python -m tests.engine.replay.record`

Expected: it ends with "dewpoint-0.1.0+abi8: recorded batches, branches, cancelled, continue_as_new, deadline,
drain, errors, evaluator, failed, failure_handler, grants, local_cel, loops, shared, simulate, stop, subflows,
variables_and_timers, version_unusable". About 1 minute.

- [ ] **Step 5: Run them again**

Run: the command of Step 2. Expected: PASS, 108 passed (the cancel test takes about 30 s: ruling 12).

- [ ] **Step 6: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add backend/src/dewpoint/engine/runtime/execution.py backend/src/dewpoint/engine/__init__.py \
  docs/superpowers/specs/2026-09-25-engine-core-design.md backend/tests/apps/worker/test_run_graph_ends.py \
  backend/tests/apps/worker/test_run_graph.py backend/tests/apps/worker/test_run_graph_continue.py \
  backend/tests/apps/worker/test_run_graph_handles.py backend/tests/apps/worker/test_run_graph_servicenow.py \
  backend/tests/engine/cel/test_profile.py backend/tests/engine/replay/dewpoint-0.1.0+abi8
git commit -m "feat(engine): every step instance's end projected; ENGINE_ABI 8 (B4b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: The milestone**

Append `### 4d-1a, milestone 1 (date)` to the ledger: the tasks' commits, the tests as run, any mid-slice ruling.
Commit (`docs(editor-4): 4d-1a milestone 1`). **Pause** for the owner's review.

---

# Milestone 2 — Simulation

### Task 6: A simulated attempt is never of unknown outcome

**Spec:** §4.1.

**Files:**
- Modify: `backend/src/dewpoint/apps/worker/activities.py` (`_transport_failed`, `_call`)
- Modify: `backend/src/dewpoint/engine/runtime/execution.py` (`_activity`, `_failed_attempt`)
- Modify: `docs/operations/runs.md`
- Modify: `backend/tests/support/plugins/testkit.py` (`SlowSimulator`, in `TESTKIT`)
- Modify: `backend/tests/apps/worker/test_activities.py`, `backend/tests/apps/worker/test_run_graph_policies.py`

**Interfaces:**
- Consumes: `SIMULATE`, `SIMULATED` (`engine.runtime.activities`); the worker's `_declared`, `_after_send`.
- Produces: `_transport_failed(e, node, *, simulated=False)`; `testkit.slow_simulator@1`.

A simulated attempt uses the configured retry policy, and is never ambiguous: nothing was sent.
- **The worker.** An `OutcomeUnknownError` from `simulate()` is the simulator's own failure: fatal, outcome
  `simulated`. A transport error or an unexpected exception from an ambiguous node is retried as any other.
- **The workflow.** A timeout and a cancellation record `simulated`, never `outcome_unknown`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/worker/test_activities.py b/backend/tests/apps/worker/test_activities.py
--- a/backend/tests/apps/worker/test_activities.py
+++ b/backend/tests/apps/worker/test_activities.py
@@ -640,3 +640,54 @@ async def test_a_declared_configs_failure_names_the_keyword_never_the_value() ->
     bad = await failure(step_activity_for(DeclaredNode, MemoryStore()),
                         step("testkit.declared@1", {"body": {"ssid": "SuperSecretValue"}}))  # fmt: skip
     assert bad.message == "The config doesn't match `testkit.declared@1`: body.ssid (schema_maxLength)."
+
+
+class _SimulatorConfig(BaseModel):
+    fails: str
+
+
+class _AmbiguousSimulator(Node):
+    """An ambiguous node whose simulator fails as `fails` says: a simulated attempt sends nothing, so none of it is an
+    unknown outcome (the simulation design §4.1)."""
+
+    type = "testkit.ambiguous_simulator"
+    version = 1
+    title = "Ambiguous simulator"
+    Config = _SimulatorConfig
+    side_effect = SideEffect.AMBIGUOUS
+
+    async def run(self, ctx: StepContext, config: _SimulatorConfig) -> BaseModel:
+        raise AssertionError("a simulated attempt never runs the node")
+
+    async def simulate(self, ctx: StepContext, config: _SimulatorConfig) -> BaseModel:
+        if config.fails == "unknown":
+            from dewpoint.sdk.errors import OutcomeUnknownError
+
+            raise OutcomeUnknownError("testkit.lost", "its answer was lost")
+        if config.fails == "transport":
+            from dewpoint.sdk.net import TransportError
+
+            class _Odd(TransportError):
+                pass
+
+            raise _Odd()
+        raise RuntimeError("a bug in the simulator")
+
+
+@pytest.mark.parametrize(
+    ("fails", "code", "retryable", "outcome"),
+    [
+        ("bug", "unexpected_error", True, None),  # as a step that isn't ambiguous: retried by the configured policy
+        ("transport", "unexpected_error", True, None),
+        ("unknown", "node_failed", False, "simulated"),  # the simulator's own failure (its code undeclared), fatal
+    ],
+)
+async def test_a_simulated_ambiguous_attempt_is_never_an_unknown_outcome(
+    fails: str, code: str, retryable: bool, outcome: str | None
+) -> None:
+    e = await failure(
+        step_activity_for(_AmbiguousSimulator, MemoryStore()),
+        step("testkit.ambiguous_simulator@1", {"fails": fails}, mode="simulate"),
+    )
+    details = e.details[0] if e.details else {}
+    assert (e.type, not e.non_retryable, details.get("outcome")) == (code, retryable, outcome)
diff --git a/backend/tests/apps/worker/test_run_graph_policies.py b/backend/tests/apps/worker/test_run_graph_policies.py
--- a/backend/tests/apps/worker/test_run_graph_policies.py
+++ b/backend/tests/apps/worker/test_run_graph_policies.py
@@ -414,6 +414,36 @@ async def test_a_timeout_after_an_ambiguous_send_is_never_retried(own_env: Workf
     assert (row.attempt, row.status, row.error_code, row.outcome) == (1, "failed", "timeout", "outcome_unknown")
 
 
+async def test_a_simulated_ambiguous_attempt_that_times_out_is_retried_by_its_policy(
+    own_env: WorkflowEnvironment,
+) -> None:
+    """The simulation design §4.1: a simulated attempt sends nothing, so its timeout is no unknown outcome. It's
+    retried as the configured policy says, and each row records `simulated`."""
+    store = MemoryStore()
+    g = graph().node("s", "testkit.slow_simulator@1", {"seconds": 3})
+    g.nodes[0]["options"].update(timeout_s=1, max_attempts=2)
+    async with workers(own_env.client, store):
+        handle = await start(own_env.client, store, g, TRIGGER, mode="simulate")
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert result.status == "failed" and result.error and result.error["code"] == "timeout"
+    rows = [(r.attempt, r.status, r.error_code, r.outcome) for r in store.steps(run_id_of(handle))]
+    assert rows == [(1, "failed", "timeout", "simulated"), (2, "failed", "timeout", "simulated")]
+    assert all("may have been sent" not in (r.error_message or "") for r in store.steps(run_id_of(handle)))
+
+
+async def test_a_simulated_ambiguous_attempt_stopped_by_the_deadline_records_simulated(
+    own_env: WorkflowEnvironment,
+) -> None:
+    store = MemoryStore()
+    g = graph().node("s", "testkit.slow_simulator@1", {"seconds": 30})
+    async with workers(own_env.client, store):
+        handle = await start(own_env.client, store, g, TRIGGER, mode="simulate", max_run_duration_s=2)
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert result.status == "deadline_exceeded"
+    [row] = store.steps(run_id_of(handle))
+    assert (row.status, row.outcome) == ("cancelled", "simulated")
+
+
 async def sent(run_id: str) -> None:
     for _ in range(200):
         if run_id in SlowSend.sent:
diff --git a/backend/tests/support/plugins/testkit.py b/backend/tests/support/plugins/testkit.py
--- a/backend/tests/support/plugins/testkit.py
+++ b/backend/tests/support/plugins/testkit.py
@@ -163,6 +163,24 @@ class SlowSend(Node):
         return Empty()
 
 
+class SlowSimulator(Node):
+    """Ambiguous, and its simulation takes `seconds`: a simulated attempt that times out or is stopped sent nothing,
+    so it's never an unknown outcome (the simulation design §4.1). It never runs live."""
+
+    type = "testkit.slow_simulator"
+    version = 1
+    title = "Slow simulator"
+    Config = SlowSendConfig
+    side_effect = SideEffect.AMBIGUOUS
+
+    async def run(self, ctx: StepContext, config: SlowSendConfig) -> Empty:
+        raise AssertionError("the slow simulator only simulates")
+
+    async def simulate(self, ctx: StepContext, config: SlowSendConfig) -> Empty:
+        await asyncio.sleep(config.seconds)
+        return Empty()
+
+
 class ReconcileOutput(BaseModel):
     found: bool
 
@@ -497,6 +515,7 @@ TESTKIT = Plugin(
         Sensitive,
         AmbiguousSend,
         SlowSend,
+        SlowSimulator,
         Reconcile,
         Blob,
         SecretBlob,
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/worker/test_activities.py
tests/apps/worker/test_run_graph_policies.py tests/engine/replay`

Expected: FAIL, 5 failed and 115 passed. Each simulated failure says `outcome_unknown`: the worker's three cases, a
timed-out attempt (`(1, 'failed', 'timeout', 'outcome_unknown')`, never retried) and one the deadline stopped.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/worker/activities.py b/backend/src/dewpoint/apps/worker/activities.py
--- a/backend/src/dewpoint/apps/worker/activities.py
+++ b/backend/src/dewpoint/apps/worker/activities.py
@@ -255,9 +255,10 @@ def _after_send(failure: _StepFailed, node: type[Node], network: AttemptNetwork
     return failure
 
 
-def _transport_failed(e: TransportError, node: type[Node]) -> _StepFailed:
-    """The SDK class's own constants, never an instance's: a plugin's subclass can't change what's shown."""
-    ambiguous = node.side_effect == SideEffect.AMBIGUOUS
+def _transport_failed(e: TransportError, node: type[Node], *, simulated: bool = False) -> _StepFailed:
+    """The SDK class's own constants, never an instance's: a plugin's subclass can't change what's shown. A simulated
+    attempt sends nothing, so it's never ambiguous (the simulation design §4.1)."""
+    ambiguous = node.side_effect == SideEffect.AMBIGUOUS and not simulated
     kind = next((k for k in _TRANSPORT if isinstance(e, k)), None)
     if kind is None:  # as any unexpected exception: an ambiguous node's request may have been sent
         message = "The node raised a network failure Dewpoint doesn't know."
@@ -299,13 +300,15 @@ async def _call(
                 return found, APPLIED
         return await instance.run(ctx, config), APPLIED
     except OutcomeUnknownError as e:
+        if step.mode == SIMULATE:  # nothing was sent: the simulator's own failure, fatal (the simulation design §4.1)
+            raise _StepFailed(*_declared(e, node), retryable=False, outcome=SIMULATED) from None
         raise _StepFailed(*_declared(e, node), retryable=False, outcome=OUTCOME_UNKNOWN) from None
     except FatalError as e:
         raise _after_send(_StepFailed(*_declared(e, node), retryable=False), node, network) from None
     except RetryableError as e:
         raise _after_send(_StepFailed(*_declared(e, node), retryable=True), node, network) from None
     except TransportError as e:
-        raise _after_send(_transport_failed(e, node), node, network) from None
+        raise _after_send(_transport_failed(e, node, simulated=step.mode == SIMULATE), node, network) from None
     except SecretIndexLimitError as e:  # a connection's secret couldn't join the index: nothing was sent (D5)
         raise _after_send(_StepFailed(SECRET_INDEX_LIMIT, str(e), retryable=False), node, network) from None
     except StoreUnavailableError as e:
@@ -319,7 +322,7 @@ async def _call(
             raise _StepFailed(SIMULATION_UNAVAILABLE, f"`{step.ref}` can't be simulated.", retryable=False) from None
         _bug("step_unexpected_error", step, e, node)
         message = f"The node raised {logs.error_class(e)}."
-        if node.side_effect == SideEffect.AMBIGUOUS:
+        if node.side_effect == SideEffect.AMBIGUOUS and step.mode != SIMULATE:
             raise _StepFailed(OUTCOME_UNKNOWN, message, retryable=False, outcome=OUTCOME_UNKNOWN) from None
         raise _StepFailed(UNEXPECTED_ERROR, message, retryable=True) from None
 
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -53,6 +53,8 @@ with workflow.unsafe.imports_passed_through():
         OUTCOME_UNKNOWN,
         PROJECT,
         REQUEST_BUDGET,
+        SIMULATE,
+        SIMULATED,
         SUBFLOW,
         BatchInput,
         BatchResult,
@@ -1770,7 +1772,9 @@ class Execution:
         retry = manifest["retry"]
         attempts = step.max_attempts or int(retry["max_attempts"])
         timeout = timedelta(seconds=step.timeout_s or float(manifest["timeout_s"]))
-        ambiguous = manifest["side_effect"] == AMBIGUOUS
+        simulated = self.mode == SIMULATE  # nothing is sent: never ambiguous, every end `simulated` (§4.1)
+        ambiguous = manifest["side_effect"] == AMBIGUOUS and not simulated
+        outcome_if_sent = SIMULATED if simulated else None
         attempt = 1
         self._attempted.add(inst)  # from here, each way it ends is rowed below
         while True:
@@ -1816,14 +1820,16 @@ class Execution:
                 ended = workflow.now().isoformat()
                 self._queue(
                     replace(
-                        row, status="failed", ended_at=ended, error_code=failure.code, error_message=failure.message
+                        row, status="failed", ended_at=ended, error_code=failure.code, error_message=failure.message,
+                        outcome=outcome_if_sent,
                     )
-                )
+                )  # fmt: skip
                 return _Effect(failure=failure, cel_mode=cel_mode)
             try:
                 await self._send(sent)
             except asyncio.CancelledError:  # the run or the scope ended before it was sent: nothing ran
-                self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat()))
+                ended = workflow.now().isoformat()
+                self._queue(replace(row, status="cancelled", ended_at=ended, outcome=outcome_if_sent))
                 raise
             try:
                 result = await workflow.execute_activity(
@@ -1847,7 +1853,7 @@ class Execution:
                     attempt += 1
                     continue
                 # The run or the scope ended: the SDK reports our own cancel as an ActivityError. Never retry it.
-                outcome = OUTCOME_UNKNOWN if ambiguous else None  # its request may have been sent
+                outcome = OUTCOME_UNKNOWN if ambiguous else outcome_if_sent  # its request may have been sent
                 self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat(), outcome=outcome))
                 raise asyncio.CancelledError from None
             if tainted_positions(result.output, self._output_shape(step.ref)):  # the tripwire (engine 2b spec §3.6)
@@ -1893,6 +1899,8 @@ class Execution:
         failure, outcome, retryable = _attempt_failed(
             e, key, row.attempt, ambiguous=ambiguous, non_retryable=retry["non_retryable"]
         )
+        if self.mode == SIMULATE:  # nothing was sent (the simulation design §4.1)
+            outcome = SIMULATED
         self._queue(
             replace(
                 row,
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -404,8 +404,8 @@ loader, the projection, and one activity per installed plugin node type. It need
   `DEWPOINT_CEL_MAX_CONCURRENT` activities at a time (default 2; match the evaluator's slots,
   [`cel-evaluator.md`](cel-evaluator.md)).
 - `DEWPOINT_WORKER_SHUTDOWN_GRACE_S` (default 30): a stopping worker lets running attempts finish this long, then
-  cancels them. A cancelled attempt ends as on a lost worker: `outcome_unknown` for an `ambiguous` node. Give the
-  process manager a stop timeout longer than this.
+  cancels them. A cancelled attempt ends as on a lost worker: `outcome_unknown` for an `ambiguous` node (a simulated
+  attempt sends nothing: `simulated`). Give the process manager a stop timeout longer than this.
 - `DEWPOINT_WORKER_SET_CURRENT` (default off): the worker makes its own build the one new runs start on. Only where
   one build runs at a time, as in Docker Compose; elsewhere, promote builds with `dewpoint deployment set-current`
   ([`deployment.md`](deployment.md)).
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 120 passed. The abi8 histories replay as recorded: the change is in the
rows, not the commands.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/worker/activities.py backend/src/dewpoint/engine/runtime/execution.py \
  docs/operations/runs.md backend/tests/support/plugins/testkit.py backend/tests/apps/worker/test_activities.py \
  backend/tests/apps/worker/test_run_graph_policies.py
git commit -m "feat(engine): a simulated attempt is never of unknown outcome (4d-1 §4.1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Flow timers are resolved but not waited in a simulation

**Spec:** §4.2.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/execution.py` (`_not_waited`; `_step`'s timer; `_queue_settled`)
- Modify: `backend/tests/apps/worker/test_run_graph_ends.py`
- Modify: `backend/tests/engine/replay/scenarios.py` (`simulated_timer`)
- Record: `backend/tests/engine/replay/dewpoint-0.1.0+abi8/simulated_timer.json` (with the commit)

**Interfaces:**
- Consumes: Task 5's `_row` and `_queue_settled`; `SIMULATE`, `SIMULATED`.
- Produces: `Execution._not_waited: dict[Instance, Any]`.

In a simulate run, `flow.delay` and `flow.wait_until` resolve and check their config as live, so a bad duration fails
as it would live. Then they don't sleep: the step succeeds at once, outcome `simulated`, output `{}`, with its
resolved config as its input preview. The run's clock isn't advanced (`run.now` stays real). Retry backoff, deadlines
and timeouts are unchanged.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_ends.py b/backend/tests/apps/worker/test_run_graph_ends.py
--- a/backend/tests/apps/worker/test_run_graph_ends.py
+++ b/backend/tests/apps/worker/test_run_graph_ends.py
@@ -206,3 +206,46 @@ async def test_inside_a_batch_every_opened_iteration_ends_each_of_its_steps(env:
     opened = {key for (_, key, _) in rows if key.startswith("l:")}
     assert "l:130" in opened and all({n for (n, k, _) in rows if k == key} == {"i", "f", "e"} for key in opened)
     assert all(status != "running" for status, _ in rows.values())
+
+
+# --- flow timers in a simulation (the simulation design §4.2) ------------------------------------------------------
+
+
+def timers(history: Any) -> list[float]:
+    """Each timer the run started: its duration, in seconds."""
+    from temporalio.api.enums.v1 import EventType
+
+    return [
+        e.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta().total_seconds()
+        for e in history.events
+        if e.event_type == EventType.EVENT_TYPE_TIMER_STARTED
+    ]
+
+
+async def test_a_simulated_delay_is_resolved_but_not_waited(env: WorkflowEnvironment) -> None:
+    """No timer of its hour (the run's deadline has its own), and its row says so: `simulated`, its resolved duration
+    as its input, its output `{}` as live."""
+    store = MemoryStore()
+    g = graph().node("d", DELAY, {"duration_s": 3600}).node("e", ECHO, {"value": 1}).edge("d", "e")
+    async with workers(env.client, store):
+        simulated = await start(env.client, store, g, {}, mode="simulate")
+        await asyncio.wait_for(simulated.result(), RESULT_TIMEOUT_S)
+        started = timers(await simulated.fetch_history())
+    assert 3600 not in started
+    [row] = [r for r in store.steps(run_id_of(simulated)) if r.node_key == "d"]
+    assert (row.status, row.outcome, row.input_preview, row.output_preview) == (
+        "succeeded", "simulated", {"duration_s": 3600}, {},
+    )  # fmt: skip
+
+
+async def test_a_simulated_delay_that_resolves_to_a_bad_value_fails_as_live(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("d", DELAY, {"duration_s": cel("0 - 5")})
+    async with workers(env.client, store):
+        results = []
+        for mode in ("live", "simulate"):
+            handle = await start(env.client, store, g, {}, mode=mode)
+            results.append(await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S))
+    (live, simulated) = results
+    assert live.status == simulated.status == "failed"
+    assert live.error and simulated.error and live.error["code"] == simulated.error["code"]
diff --git a/backend/tests/engine/replay/scenarios.py b/backend/tests/engine/replay/scenarios.py
--- a/backend/tests/engine/replay/scenarios.py
+++ b/backend/tests/engine/replay/scenarios.py
@@ -6,8 +6,8 @@ error policy; variables and timers; stop, fail, simulation and the deadline; CEL
 batched loops, sub-flows, the failure handler, grants, continue-as-new and drain mode. 2a-3c turns local CEL on:
 expressions run in the workflow, with the yield-point timer, and the rest go to `cel.evaluate`. It also records a
 cancelled run and a version this build can't compile. 2b-4b's engine blockers add a value several binding sets share,
-claimed once (#26). A scenario that runs sub-flows builds its graph against the
-recorder's store, which publishes them first."""
+claimed once (#26). Editor 4d-1a adds a simulated timer, not waited (the simulation design §4.2). A scenario that
+runs sub-flows builds its graph against the recorder's store, which publishes them first."""
 
 from collections.abc import Callable
 from dataclasses import dataclass, field
@@ -249,4 +249,8 @@ def scenarios() -> dict[str, Scenario]:
         "shared": Scenario(_shared(), trigger={"s": "x" * 20_000}),
         "cancelled": Scenario(_graph().node("d", "flow.delay@1", {"duration_s": 3_600}), cancel=True),
         "version_unusable": Scenario(_graph().node("a", ECHO, {"value": 1}), unusable=True),
+        "simulated_timer": Scenario(
+            _graph().node("d", "flow.delay@1", {"duration_s": 3_600}).node("a", ECHO, {"value": 1}).edge("d", "a"),
+            options={"mode": "simulate"},
+        ),
     }
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/worker/test_run_graph_ends.py tests/engine/replay`

Expected: FAIL, 2 failed and 61 passed:
- the simulated delay started its hour's timer (`assert 3600 not in [2591999.99…, 3600.0]`);
- `simulated_timer` isn't recorded ("run `uv run python -m tests.engine.replay.record`").

The bad-value test passes already: it's a guard.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -297,6 +297,7 @@ class Execution:
         self._attempted: set[Instance] = set()
         self._finished: set[Instance] = set()
         self._effects: dict[Instance, dict[str, Any]] = {}
+        self._not_waited: dict[Instance, Any] = {}  # a simulated timer's resolved config, for its row (§4.2)
         self._projects = 0
         self._timers: dict[Instance, datetime] = {}  # a timer step asleep -> its wake time
         self._resume: list[Instance] = []  # timer steps a snapshot carried over: they re-arm first
@@ -739,12 +740,15 @@ class Execution:
             if not step.control:
                 continue
             error = result.get("error")
+            waited = self._not_waited.pop(inst, None)  # a simulated timer: nothing waited, so nothing happened (§4.2)
             self._queue(
                 self._row(
                     inst,
                     "failed" if error else "succeeded",
                     started_at=self._started.get(inst),
                     ended_at=now,
+                    input_preview=self._preview(waited) if waited is not None else None,
+                    outcome=SIMULATED if waited is not None else None,
                     output_preview=self._preview(result.get("output")),
                     error_code=error["code"] if error else None,
                     error_message=error["message"] if error else None,
@@ -1341,6 +1345,9 @@ class Execution:
         if wake is not None:
             if cel_mode is not None:
                 self._cel_modes[inst] = cel_mode
+            if self.mode == SIMULATE:  # resolved and checked as live, then not waited (the simulation design §4.2)
+                self._not_waited[inst] = config
+                return _Effect(output={}, cel_mode=self._cel_modes.get(inst))
             return await self._timer(inst, wake)
         return _Effect(
             output=decision.output,
```

- [ ] **Step 4: Record the new scenario**

Run: `uv run --frozen python -m tests.engine.replay.record`. Expected: "dewpoint-0.1.0+abi8: recorded
simulated_timer".

- [ ] **Step 5: Run them again**

Run: the command of Step 2. Expected: PASS, 64 passed.

- [ ] **Step 6: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add backend/src/dewpoint/engine/runtime/execution.py backend/tests/apps/worker/test_run_graph_ends.py \
  backend/tests/engine/replay/scenarios.py backend/tests/engine/replay/dewpoint-0.1.0+abi8
git commit -m "feat(engine): flow timers resolved but not waited in a simulation (4d-1 §4.2)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# Milestone 3 — S2 and the close

### Task 8: A single step's seed contract

**Spec:** §5.1, §5.2.

**Files:**
- Create: `backend/src/dewpoint/engine/graph/seeds.py`
- Create: `backend/tests/engine/graph/test_seeds.py`

**Interfaces:**
- Consumes: the validator's `analyze`, `site_of`, `Analysis`, `ValidationContext` and `_Validator._resolve(site, p,
  report=False)`; `graph.schemas.Resolved` and `json_types`; `graph.schema_messages.explain`; `graph.values`
  (`iter_values`, `RefValue`, `TemplateValue`, `TemplateRef`, `CelValue`, `parse_ref`, `pointer_str`);
  `cel.record.ExpressionRecord`; `cel.runtime.compile_checked`, `cel.ast.chains`, `cel.guards.facts_at` (with
  `guards.non_null` and `guards.shape` too);
  jsonschema's `Draft202012Validator` (its errors' `context` for a choice's branches).
- Produces:
  - `CONTROL_TARGETS`; `is_target(ref: str, control: bool) -> bool`;
  - `SeedEntry(pointer, types, required, nullable, sensitive, holds=(), schema=None, inner=(), null_ok=(),
    keeps_required=False)`; `Hold(pointer, given=0)` and `Hold.text`; `EVERY` (`-1`, each element, `*` in a
    pointer);
  - `SeedContract(entries=(), aliases={}, refused=None)`; `SeedProblem(code, pointer, message)`;
  - `contract(graph, ctx, node) -> SeedContract`; `contract_of(analysis, node) -> SeedContract`;
  - `check(contract, values, absent) -> list[SeedProblem]`;
  - the codes `SEED_MISSING`, `SEED_ALIAS`, `SEED_UNKNOWN`, `SEED_INVALID`;
  - the refusals `NO_ANALYSIS`, `NO_STEP`, `NOT_ALONE`, `READS_EVERY`.

The contract asks the validator's converged analysis and resolver, never a copy of their rules:
- **Reads.** The step's refs, template parts, and each CEL value's chains, from its expression checked as validation
  checked it, with the paths its guards prove present at each. It leaves out what the run binds (`run.*`). A
  filter's predicate `item` and `index` are no seeds: a read of `item…` is one of each element of the list the
  filter's `items` path names (`EVERY`), held where that list is; when the items are computed, a strict one keeps
  the schema's `required` in what they read (ruling 16).
- **Normalized** (rulings 1–3). A read through a list index is the whole list. The innermost loop's
  `loops.<key>.item` and `.index` are `/item` and `/index`; their aliases are refused. A read inside another merges
  into the outer one.
- **Obligations, per use**, the strictest winning, guards included (ruling 1).
- **The check** (rulings 2 and 4). Every entry is in exactly one of `values` and `absent`: absent only where
  optional, null only where nullable. A value fits its schema as it stands, and each read inside it its own;
  inside it, presence and null follow the uses (their errors excused, in a choice's branches too). No pointer the
  contract doesn't list; an alias, or a path below one, names its canonical pointer.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/engine/graph/test_seeds.py b/backend/tests/engine/graph/test_seeds.py
new file mode 100644
--- /dev/null
+++ b/backend/tests/engine/graph/test_seeds.py
@@ -0,0 +1,351 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A single step's seed contract (S2; the simulation design §5.2): its reads as pointers, with the resolver's
+obligations, normalized; and the seeds checked against it."""
+
+import copy
+from typing import Any
+
+from dewpoint.engine.graph.seeds import (
+    NOT_ALONE,
+    SEED_ALIAS,
+    SEED_INVALID,
+    SEED_MISSING,
+    SEED_UNKNOWN,
+    SeedContract,
+    check,
+    contract,
+)
+from dewpoint.engine.graph.validate import ValidationContext, validate
+from dewpoint.plugins.flow import PLUGIN as FLOW
+from tests.support.catalog import catalog
+from tests.support.graphs import G, cel, nid, ref, template
+from tests.support.plugins.testkit import TESTKIT
+
+CTX = ValidationContext(catalog=catalog(FLOW, TESTKIT))
+ECHO, LOOP, FILTER, TRANSFORM = "testkit.echo@1", "flow.loop@1", "flow.filter@1", "flow.transform@1"
+INPUT: dict[str, Any] = {  # closed objects: an undeclared key could be a secret, which would taint every read
+    "type": "object",
+    "properties": {
+        "site": {"type": "string"},
+        "note": {"type": ["string", "null"]},
+        "secret": {"type": "string", "x-sensitive": True},
+        "aps": {"type": "array", "items": {"type": "object", "properties": {"mac": {"type": "string"}},
+                                           "required": ["mac"], "additionalProperties": False}},
+        "owner": {"type": "object", "properties": {"name": {"type": "string"}, "tag": {"type": "string"}},
+                  "required": ["name"], "additionalProperties": False},
+    },
+    "required": ["site", "aps", "secret", "owner"],
+    "additionalProperties": False,
+}  # fmt: skip
+
+
+def graph() -> G:
+    g = G()
+    g.settings = {
+        "input_schema": copy.deepcopy(INPUT),
+        "vars_schema": {"type": "object", "properties": {"n": {"type": "integer", "default": 0}}},
+    }
+    return g
+
+
+def of(g: G, key: str) -> SeedContract:
+    """The contract of a draft that validates: a use the validator refuses would say nothing of the rule."""
+    built = g.build()
+    assert [d.code for d in validate(built, CTX).diagnostics if d.severity == "error"] == []
+    return contract(built, CTX, nid(key))
+
+
+def table(c: SeedContract) -> dict[str, tuple[Any, ...]]:
+    return {
+        e.pointer: (e.types, e.required, e.nullable, e.sensitive, tuple(h.text for h in e.holds)) for e in c.entries
+    }
+
+
+def test_refs_templates_and_cel_reads_are_entries_with_the_resolvers_obligations() -> None:
+    fields = {
+        "site": template("at ", {"ref": "trigger.site"}),
+        "note": ref("trigger.note", default=None),
+        "secret": ref("trigger.secret"),
+        "n": cel("vars.n + 1"),
+        "when": cel("run.now"),  # the run binds it: never a seed
+    }
+    g = graph().node("t", TRANSFORM, {"fields": fields})
+    assert table(of(g, "t")) == {
+        "/trigger/note": (("string",), False, True, False, ()),  # null is `nullable`, not a type
+        "/trigger/secret": (("string",), True, False, True, ()),
+        "/trigger/site": (("string",), True, False, False, ()),
+        "/vars/n": (("integer",), True, False, False, ()),
+    }
+
+
+def test_a_read_through_an_index_is_the_whole_list_and_a_read_inside_another_is_the_outer_one() -> None:
+    fields = {
+        "first": ref("trigger.aps[0].mac", default=""),
+        "name": ref("trigger.owner.name"),
+        "owner": cel("trigger.owner"),
+    }
+    g = graph().node("t", TRANSFORM, {"fields": fields})
+    rows = table(of(g, "t"))
+    assert rows["/trigger/aps"][0] == ("array",) and rows["/trigger/owner"][4] == ("/name",)
+    assert set(rows) == {"/trigger/aps", "/trigger/owner"}
+
+
+def test_a_value_every_use_defaults_may_be_absent_or_null() -> None:
+    """The strictest use wins (§5.2): `site` is always there, but every use here gives a default, so the person may
+    leave it absent or null to see the default; one strict use makes it required, and null then fits only where the
+    schema allows it."""
+    defaulted = {"a": ref("trigger.site", default="HQ"), "b": template({"ref": "trigger.site", "default": "HQ"})}
+    c = of(graph().node("t", TRANSFORM, {"fields": defaulted}), "t")
+    assert table(c)["/trigger/site"] == (("string",), False, True, False, ())
+    assert check(c, {}, ["/trigger/site"]) == [] and check(c, {"/trigger/site": None}, []) == []
+    strict = of(graph().node("t", TRANSFORM, {"fields": {**defaulted, "c": cel("trigger.site")}}), "t")
+    assert table(strict)["/trigger/site"] == (("string",), True, False, False, ())
+
+
+def test_a_child_is_held_only_where_a_use_reads_it_strictly() -> None:
+    fields = {"owner": cel("trigger.owner"), "name": ref("trigger.owner.name", default="?"),
+              "tag": cel("has(trigger.owner.tag) ? trigger.owner.tag : ''")}  # fmt: skip
+    rows = table(of(graph().node("t", TRANSFORM, {"fields": fields}), "t"))
+    assert rows["/trigger/owner"][1:] == (True, False, False, ())  # neither `name` (defaulted) nor `tag` (guarded)
+    strict = {**fields, "name": ref("trigger.owner.name")}
+    assert table(of(graph().node("t", TRANSFORM, {"fields": strict}), "t"))["/trigger/owner"][4] == ("/name",)
+
+
+def test_the_innermost_loops_item_is_canonical_and_its_alias_refused() -> None:
+    g = graph().node("l", LOOP, {"items": ref("trigger.aps")})
+    g.node("x", ECHO, {"value": {"a": ref("item.mac"), "b": ref("loops.l.index")}}).edge("l", "x", "body")
+    c = of(g, "x")
+    assert set(table(c)) == {"/item/mac", "/index"}
+    assert c.aliases == {"/loops/l/item": "/item", "/loops/l/index": "/index"}
+    problems = check(c, {"/loops/l/item": {"mac": "m"}, "/index": 0}, [])
+    assert [(p.code, p.pointer) for p in problems] == [(SEED_MISSING, "/item/mac"), (SEED_ALIAS, "/loops/l/item")]
+    [_, below] = check(c, {"/loops/l/item/mac": "m", "/index": 0}, [])  # a path below an alias is the alias's too
+    assert (below.code, below.pointer) == (SEED_ALIAS, "/loops/l/item/mac") and "/item/mac" in below.message
+
+
+def test_a_read_a_guard_proves_present_may_be_absent() -> None:
+    """Spec §5.2: a guarded CEL read tolerates absence, of a value the schema says is always there too. A read below
+    a guarded one is held only when the value is given."""
+    c = of(graph().node("t", TRANSFORM, {"fields": {"s": cel("has(trigger.site) ? trigger.site : ''")}}), "t")
+    assert table(c)["/trigger/site"] == (("string",), False, False, False, ())
+    owner = cel("has(trigger.owner) ? trigger.owner.name : ''")
+    o = of(graph().node("t", TRANSFORM, {"fields": {"n": owner}}), "t")
+    assert table(o)["/trigger/owner"][1:] == (False, False, False, ("/name",))
+    assert check(o, {}, ["/trigger/owner"]) == [] and [p.code for p in check(o, {"/trigger/owner": {}}, [])] == [
+        SEED_INVALID
+    ]
+
+
+def test_a_value_is_checked_against_its_whole_schema_and_each_read_inside_it() -> None:
+    """Merging a read into the outer one keeps its type: a child of the wrong type, or a list's element, is refused,
+    and so is a variable read inside the variables given whole."""
+    fields = {"owner": cel("trigger.owner"), "name": ref("trigger.owner.name"), "aps": cel("size(trigger.aps)")}
+    c = of(graph().node("t", TRANSFORM, {"fields": fields}), "t")
+    assert check(c, {"/trigger/owner": {"name": "n"}, "/trigger/aps": [{"mac": "m"}]}, []) == []
+    found = check(c, {"/trigger/owner": {"name": 42}, "/trigger/aps": [{"mac": 5}]}, [])
+    assert [(p.code, p.pointer) for p in found] == [(SEED_INVALID, "/trigger/aps"), (SEED_INVALID, "/trigger/owner")]
+    assert found[1].message.startswith("At /name: ")
+    v = of(graph().node("t", TRANSFORM, {"fields": {"k": cel("size(vars)"), "n": ref("vars.n")}}), "t")
+    assert check(v, {"/vars": {"n": 1}}, []) == [] and [p.code for p in check(v, {"/vars": {"n": "x"}}, [])] == [
+        SEED_INVALID
+    ]
+
+
+def test_inside_a_value_presence_and_null_come_from_the_uses_never_the_schemas_required() -> None:
+    """§5.2: a read inside a value with a default tolerates its absence and null there, as the run does; its schema
+    still types it. One strict read makes it a path the value must hold, not null."""
+    defaulted = {"owner": cel("trigger.owner"), "name": ref("trigger.owner.name", default="?")}
+    c = of(graph().node("t", TRANSFORM, {"fields": defaulted}), "t")
+    assert check(c, {"/trigger/owner": {}}, []) == [] and check(c, {"/trigger/owner": {"name": None}}, []) == []
+    assert [p.code for p in check(c, {"/trigger/owner": {"name": 42}}, [])] == [SEED_INVALID]
+    strict = of(graph().node("t", TRANSFORM, {"fields": {**defaulted, "name": ref("trigger.owner.name")}}), "t")
+    for owner in ({}, {"name": None}):
+        assert [p.code for p in check(strict, {"/trigger/owner": owner}, [])] == [SEED_INVALID]
+    v = of(graph().node("t", TRANSFORM, {"fields": {"k": cel("size(vars)"), "n": ref("vars.n", default=9)}}), "t")
+    assert check(v, {"/vars": {"n": None}}, []) == [] and check(v, {"/vars": {}}, []) == []
+
+
+def with_input(**fields: Any) -> G:
+    """The test input, with `fields` added as required properties."""
+    g = graph()
+    g.settings["input_schema"]["properties"].update(fields)
+    g.settings["input_schema"]["required"] += list(fields)
+    return g
+
+
+def test_presence_tested_by_a_schema_keeps_its_meaning() -> None:
+    """`required` inside `not` or `if` is a test of the value, never an obligation excused away."""
+    person = {
+        "type": "object",
+        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
+        "not": {"required": ["name", "age"]},
+        "additionalProperties": False,
+    }
+    mode = {"type": "object", "properties": {"mode": {"type": "integer"}, "x": {}}, "if": {"required": ["mode"]},
+            "then": {"properties": {"x": {"type": "integer"}}}, "else": {"properties": {"x": {"type": "string"}}},
+            "additionalProperties": False}  # fmt: skip
+    fields = {"p": cel("trigger.person"), "m": cel("trigger.mode")}
+    c = of(with_input(person=person, mode=mode).node("t", TRANSFORM, {"fields": fields}), "t")
+    assert check(c, {"/trigger/person": {"name": "n"}, "/trigger/mode": {"x": "s"}}, []) == []
+    found = check(c, {"/trigger/person": {"name": "n", "age": 1}, "/trigger/mode": {"mode": 1, "x": "s"}}, [])
+    assert [(p.code, p.pointer) for p in found] == [(SEED_INVALID, "/trigger/mode"), (SEED_INVALID, "/trigger/person")]
+
+
+def test_a_null_the_uses_take_is_taken_inside_a_choice() -> None:
+    either = {
+        "anyOf": [
+            {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False},
+            {"type": "object", "properties": {"name": {"type": "integer"}}, "additionalProperties": False},
+        ]
+    }
+    fields = {"e": cel("trigger.either"), "n": ref("trigger.either.name", default=None)}
+    c = of(with_input(either=either).node("t", TRANSFORM, {"fields": fields}), "t")
+    assert check(c, {"/trigger/either": {"name": None}}, []) == []
+    assert [p.code for p in check(c, {"/trigger/either": {"name": [1]}}, [])] == [SEED_INVALID]
+
+
+def test_a_read_through_an_index_keeps_its_allowances_in_the_whole_list() -> None:
+    """`aps[0].mac` with a default takes null at `/0/mac`; an element no use reads keeps its schema's type."""
+    c = of(graph().node("t", TRANSFORM, {"fields": {"m": ref("trigger.aps[0].mac", default="fallback")}}), "t")
+    assert check(c, {"/trigger/aps": [{"mac": None}]}, []) == []
+    assert [p.code for p in check(c, {"/trigger/aps": [{"mac": "a"}, {"mac": None}]}, [])] == [SEED_INVALID]
+
+
+def test_a_filters_predicate_reads_bind_each_element_of_the_list_it_filters() -> None:
+    """`item` and `index` are never seeds, but what the predicate reads of each element is the filtered list's to
+    hold: strictly read, every element has it; guarded, none needs it. A list computed from a value can't be traced
+    so: what it's computed from keeps its schema's `required`."""
+    strict = of(graph().node("f", FILTER, {"items": ref("trigger.aps"), "predicate": cel("item.mac == 'm'")}), "f")
+    assert check(strict, {"/trigger/aps": [{"mac": "m"}]}, []) == [] and check(strict, {"/trigger/aps": []}, []) == []
+    [problem] = check(strict, {"/trigger/aps": [{"mac": "m"}, {}]}, [])
+    assert (problem.code, problem.pointer, problem.message) == (
+        SEED_INVALID,
+        "/trigger/aps",
+        "This value must hold /*/mac.",
+    )
+    guarded = cel("has(item.mac) && item.mac == 'm'")
+    g = of(graph().node("f", FILTER, {"items": ref("trigger.aps"), "predicate": guarded}), "f")
+    assert check(g, {"/trigger/aps": [{}]}, []) == []
+    computed = of(
+        graph().node("f", FILTER, {"items": cel("trigger.aps + []"), "predicate": cel("item.mac == 'm'")}), "f"
+    )
+    assert [p.code for p in check(computed, {"/trigger/aps": [{}]}, [])] == [SEED_INVALID]
+
+
+def test_a_guarded_read_inside_a_value_holds_only_where_its_guard_is_there() -> None:
+    """Merged into a value read whole, `has(boss.profile) ? boss.profile.name : …` keeps its condition: no `profile`
+    is fine; a `profile` given must hold `name`."""
+    profile = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"],
+               "additionalProperties": False}  # fmt: skip
+    boss = {"type": "object", "properties": {"profile": profile}, "additionalProperties": False}
+    fields = {"o": cel("trigger.boss"), "n": cel("has(trigger.boss.profile) ? trigger.boss.profile.name : 'absent'")}
+    c = of(with_input(boss=boss).node("t", TRANSFORM, {"fields": fields}), "t")
+    assert table(c)["/trigger/boss"][4] == ("/profile/name where /profile is there and isn't null",)
+    assert (
+        check(c, {"/trigger/boss": {}}, []) == [] and check(c, {"/trigger/boss": {"profile": {"name": "x"}}}, []) == []
+    )
+    [problem] = check(c, {"/trigger/boss": {"profile": {}}}, [])
+    assert problem.message == "This value must hold /profile/name where /profile is there and isn't null."
+
+
+def test_a_read_a_non_null_test_guards_holds_only_where_that_isnt_null() -> None:
+    """`profile != null ? profile.name : …` keeps its condition, merged or mapped: a null `profile` is fine, an object
+    must hold `name`. The comparison still reads `profile` itself, so it must be there."""
+    profile = {"type": ["object", "null"], "properties": {"name": {"type": "string"}}, "required": ["name"],
+               "additionalProperties": False}  # fmt: skip
+    boss = {
+        "type": "object",
+        "properties": {"profile": profile},
+        "required": ["profile"],
+        "additionalProperties": False,
+    }
+    guarded = "trigger.boss.profile != null ? trigger.boss.profile.name : 'absent'"
+    c = of(with_input(boss=boss).node("t", TRANSFORM, {"fields": {"o": cel("trigger.boss"), "n": cel(guarded)}}), "t")
+    for ok in ({"profile": None}, {"profile": {"name": "x"}}):
+        assert check(c, {"/trigger/boss": ok}, []) == [], ok
+    for bad in ({"profile": {}}, {}):
+        assert [p.code for p in check(c, {"/trigger/boss": bad}, [])] == [SEED_INVALID], bad
+    bosses = {"type": "array", "items": boss}
+    predicate = cel("item.profile != null ? item.profile.name == 'x' : false")
+    f = of(with_input(bosses=bosses).node("f", FILTER, {"items": ref("trigger.bosses"), "predicate": predicate}), "f")
+    assert check(f, {"/trigger/bosses": [{"profile": None}, {"profile": {"name": "x"}}]}, []) == []
+    assert [p.code for p in check(f, {"/trigger/bosses": [{"profile": {}}]}, [])] == [SEED_INVALID]
+
+
+def test_a_filters_reads_through_its_items_keep_their_conditions() -> None:
+    """`items` through an index, with a default: the list may be missing or empty (the default, or no element); the
+    elements there hold what the predicate reads. A list its items default may be null too."""
+    aps = {"type": "array", "items": {"type": "object", "properties": {"mac": {"type": "string"}}, "required": ["mac"],
+                                      "additionalProperties": False}}  # fmt: skip
+    groups = {"type": "array", "items": {"type": "object", "properties": {"aps": aps}, "additionalProperties": False}}
+    items = ref("trigger.groups[0].aps", default=[])
+    c = of(with_input(groups=groups).node("f", FILTER, {"items": items, "predicate": cel("item.mac == 'm'")}), "f")
+    for ok in ([], [{}], [{"aps": []}], [{"aps": [{"mac": "m"}]}]):
+        assert check(c, {"/trigger/groups": ok}, []) == [], ok
+    [problem] = check(c, {"/trigger/groups": [{"aps": [{}]}]}, [])
+    assert problem.message == "This value must hold /0/aps/*/mac where /0/aps is there and isn't null."
+    d = of(
+        graph().node("f", FILTER, {"items": ref("trigger.aps", default=[]), "predicate": cel("item.mac == 'm'")}), "f"
+    )
+    assert check(d, {"/trigger/aps": None}, []) == [] and check(d, {}, ["/trigger/aps"]) == []
+
+
+def test_a_computed_list_keeps_required_only_for_a_strict_read() -> None:
+    computed = cel("trigger.aps + []")
+    guarded = of(graph().node("f", FILTER, {"items": computed, "predicate": cel("has(item.mac) && item.mac == 'm'")}),
+                 "f")  # fmt: skip
+    assert check(guarded, {"/trigger/aps": [{}]}, []) == []
+    strict = of(graph().node("f", FILTER, {"items": computed, "predicate": cel("item.mac == 'm'")}), "f")
+    assert [p.code for p in check(strict, {"/trigger/aps": [{}]}, [])] == [SEED_INVALID]
+
+
+def test_a_null_a_default_takes_stands_for_a_value_that_picks_its_own_branch() -> None:
+    """`oneOf` as `anyOf` once the uses' allowances are excused: a real value there would match one branch."""
+    profile = {
+        "oneOf": [
+            {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False},
+            {"type": "object", "properties": {"name": {"type": "integer"}}, "additionalProperties": False},
+        ]
+    }
+    owner = {
+        "type": "object",
+        "properties": {"profile": profile},
+        "required": ["profile"],
+        "additionalProperties": False,
+    }
+    fields = {"o": cel("trigger.boss"), "n": ref("trigger.boss.profile.name", default=None)}
+    c = of(with_input(boss=owner).node("t", TRANSFORM, {"fields": fields}), "t")
+    assert check(c, {"/trigger/boss": {"profile": {"name": None}}}, []) == []
+    assert [p.code for p in check(c, {"/trigger/boss": {"profile": {"name": [1]}}}, [])] == [SEED_INVALID]
+
+
+def test_a_filters_per_element_names_are_never_seeds() -> None:
+    g = graph().node("f", FILTER, {"items": ref("trigger.aps"), "predicate": cel("item.mac == trigger.site")})
+    assert set(table(of(g, "f"))) == {"/trigger/aps", "/trigger/site"}
+
+
+def test_a_step_that_cant_run_alone_has_no_contract() -> None:
+    g = graph().node("l", LOOP, {"items": ref("trigger.aps")}).node("x", ECHO, {"value": 1}).edge("l", "x", "body")
+    assert of(g, "l").refused == NOT_ALONE
+
+
+def test_seeds_are_checked_against_the_contract() -> None:
+    fields = {"note": ref("trigger.note", default=None), "site": ref("trigger.site")}
+    g = graph().node("t", TRANSFORM, {"fields": fields})
+    c = of(g, "t")
+    assert check(c, {"/trigger/site": "HQ", "/trigger/note": None}, []) == []
+    assert check(c, {"/trigger/site": "HQ"}, ["/trigger/note"]) == []  # optional: absent
+    found = check(c, {"/trigger/site": None, "/run/now": "x"}, ["/trigger/note", "/trigger/note"])
+    assert [(p.code, p.pointer) for p in found] == [(SEED_UNKNOWN, "/run/now"), (SEED_INVALID, "/trigger/site")]
+    assert [p.code for p in check(c, {"/trigger/note": None}, ["/trigger/site"])] == [SEED_MISSING]
+    assert [p.code for p in check(c, {"/trigger/site": 5, "/trigger/note": None}, [])] == [SEED_INVALID]
+
+
+def test_a_whole_number_is_a_number_and_null_needs_a_nullable_path() -> None:
+    g = graph()
+    g.settings["input_schema"]["properties"]["ratio"] = {"type": "number"}
+    g.settings["input_schema"]["required"].append("ratio")
+    g.node("t", TRANSFORM, {"fields": {"r": ref("trigger.ratio")}})
+    c = of(g, "t")
+    assert check(c, {"/trigger/ratio": 2}, []) == [] and check(c, {"/trigger/ratio": 2.5}, []) == []
+    assert [p.code for p in check(c, {"/trigger/ratio": "2"}, [])] == [SEED_INVALID]
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/engine/graph/test_seeds.py tests/engine/replay`

Expected: FAIL, 1 error and 53 passed: "No module named 'dewpoint.engine.graph.seeds'".

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/engine/graph/seeds.py b/backend/src/dewpoint/engine/graph/seeds.py
new file mode 100644
--- /dev/null
+++ b/backend/src/dewpoint/engine/graph/seeds.py
@@ -0,0 +1,526 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A single step's seed contract (S2; the simulation design §5.2): what one step of a draft reads, as root-anchored
+JSON pointers a person gives values for when the step runs alone.
+
+It asks the validator's converged analysis (`analyze`), its resolver and its guard facts (`cel.guards`), as the data
+tree does (`scope.py`), never a copy of their rules. The reads are the step's own context: its refs, its template
+parts, and each CEL value's chains, minus what a run binds itself (`run.*`) and what a filter binds per element (its
+predicate's `item` and `index`). Each entry's obligations are its uses', the strictest winning: it's required unless
+every use tolerates its absence (a default, a `has()` test, or a read a guard proves present); null only where its
+schema allows it or every use has a default; sensitive where its taint says. A value given is checked against the
+resolver's schema for it, and each read inside it against its own, as the schema stands: inside it, presence and null
+come from the uses too (a path a use reads strictly must be there; null where the schema allows it or every use
+reading through it has a default), so a schema's `required` (where it obliges, never where it tests) and a null the
+uses take are no refusal, in a choice's branches too.
+
+Normalized: a read through a list index is the whole list; the innermost loop's `loops.<key>.item` and `.index` are
+`/item` and `/index` (their aliases, and paths below them, are refused, `seed_alias`); a read inside another is the
+outer one, which carries the inner reads as paths its value must hold."""
+
+import dataclasses
+import uuid
+from collections.abc import Mapping, Sequence
+from dataclasses import dataclass, field
+from typing import Any, Literal, NamedTuple
+
+from jsonschema import Draft202012Validator
+
+from dewpoint.engine.cel import ast, guards, runtime
+from dewpoint.engine.cel.record import ExpressionRecord
+from dewpoint.engine.graph.schema_messages import explain
+from dewpoint.engine.graph.schemas import Resolved, json_types
+from dewpoint.engine.graph.validate import Analysis, ValidationContext, analyze, site_of
+from dewpoint.engine.graph.values import (
+    CelValue,
+    RefPath,
+    RefSyntaxError,
+    RefValue,
+    TemplateRef,
+    TemplateValue,
+    iter_values,
+    parse_ref,
+    pointer_str,
+)
+from dewpoint.engine.registry import control as C
+
+# The control steps a single-step simulation runs (D-s1); every action (plugin) step runs too.
+CONTROL_TARGETS = frozenset({C.IF, C.SWITCH, C.FILTER, C.TRANSFORM, C.SET_VARIABLES})
+SEED_MISSING, SEED_ALIAS, SEED_UNKNOWN, SEED_INVALID = "seed_missing", "seed_alias", "seed_unknown", "seed_invalid"
+NO_ANALYSIS = "The saved draft has problems that stop its steps being read. Fix them first."
+NO_STEP = "This step isn't in the saved draft."
+NOT_ALONE = "This step can't be simulated alone: simulate the workflow to see it run."
+READS_EVERY = "This step reads every step's results at once, so it can't be simulated alone."
+JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object", "null"})
+Kind = Literal["strict", "defaulted", "cel", "presence"]
+Segs = tuple[str | int, ...]
+EVERY = -1  # in a read's path, each element of a list (a filter's `item`); a pointer shows it as `*`
+_ANY = Resolved(None, False)  # a resolution no question here asks of
+
+
+class Hold(NamedTuple):
+    """A path, relative to its entry, that a value given must hold. Its first `given` segments are a condition: where
+    they're there and not null, the rest must be (a guard's, or the list a filter reads each element of). `*` is each
+    element."""
+
+    pointer: str
+    given: int = 0
+
+    @property
+    def text(self) -> str:
+        if not self.given:
+            return self.pointer
+        return f"{self.pointer} where /{'/'.join(self.pointer.split('/')[1 : self.given + 1])} is there and isn't null"
+
+
+@dataclass(frozen=True)
+class SeedEntry:
+    """One value the step reads. `types`: the JSON types it may have (() when any value); `holds`: what a read inside
+    it needs there (`Hold`); `schema`: the resolver's for it, which a value given is checked against; `inner`: each
+    read inside it, by relative pointer, with its own schema; `null_ok`: relative pointers where null is taken (its
+    schema allows it, or every use reading through it does)."""
+
+    pointer: str
+    types: tuple[str, ...]
+    required: bool
+    nullable: bool
+    sensitive: bool
+    holds: tuple[Hold, ...] = ()
+    schema: Mapping[str, Any] | None = field(default=None, compare=False, repr=False)
+    inner: tuple[tuple[str, Mapping[str, Any] | None], ...] = field(default=(), compare=False, repr=False)
+    null_ok: tuple[str, ...] = field(default=(), compare=False, repr=False)
+    keeps_required: bool = field(default=False, compare=False, repr=False)  # a computed filter list reads it
+
+
+@dataclass(frozen=True)
+class SeedContract:
+    entries: tuple[SeedEntry, ...] = ()
+    aliases: Mapping[str, str] = field(default_factory=dict)  # an alias pointer -> its canonical one
+    refused: str | None = None  # why the step can't run alone
+
+
+@dataclass(frozen=True)
+class SeedProblem:
+    code: str
+    pointer: str
+    message: str
+
+
+def is_target(ref: str, control: bool) -> bool:
+    return not control or ref in CONTROL_TARGETS
+
+
+def escape(segment: str | int) -> str:
+    return str(segment).replace("~", "~0").replace("/", "~1")
+
+
+def _segments(p: RefPath) -> list[str | int]:
+    """A reference's pointer segments, root first: the run binds `run`, the rest is the scope's."""
+    if p.root in ("steps", "loops"):
+        return [p.root, str(p.name), str(p.section), *p.rest]
+    if p.root == "vars":
+        return ["vars", *([str(p.name)] if p.name is not None else []), *p.rest]
+    return [p.root, *p.rest]
+
+
+def _cut(segments: list[str | int]) -> list[str | int]:
+    """A read through a list index is the whole list: a seed never builds a list with gaps."""
+    for i, seg in enumerate(segments):
+        if isinstance(seg, int):
+            return segments[:i]
+    return segments
+
+
+def _ref_of(segments: Sequence[str | int]) -> RefPath | None:
+    text = ""
+    for i, seg in enumerate(segments):
+        if isinstance(seg, int):
+            text += f"[{seg}]"
+        elif i == 0:
+            text = seg
+        else:
+            text += f".{seg}"
+    try:
+        return parse_ref(text)
+    except RefSyntaxError:
+        return None
+
+
+Read = tuple[list[str | int], Kind, frozenset[Segs], frozenset[Segs]]  # path, kind, proven present, proven not null
+
+
+def _cel_reads(record: ExpressionRecord) -> list[Read] | str:
+    """A CEL value's reads, as validation checked it: each chain from a root (a typed path read whole), its kind, the
+    paths its guards prove present wherever it's read (`has()`), and those they prove not null (`!= null`, or an
+    object by `type(x) == type({})`), from the validator's own `guards.facts_at`. A refusal when it can't be read so,
+    or reads every step's results at once."""
+    try:
+        checked = runtime.compile_checked(record.expr, record.declarations).checked
+    except runtime.CompileError:
+        return NO_ANALYSIS
+    facts = guards.facts_at(checked.expr)
+    non_null = guards.facts_at(checked.expr, guards.non_null)
+    shapes = guards.facts_at(checked.expr, guards.shape)
+    reads: list[Read] = []
+    short: set[str] = set()
+    long: set[str] = set()
+    for chain in ast.chains(checked.expr):
+        proven = frozenset(facts.get(chain.expr_id, frozenset()))
+        set_ = frozenset(non_null.get(chain.expr_id, frozenset()) | shapes.get(chain.expr_id, frozenset()))
+        if "." in chain.ident:
+            p = _ref_of(chain.ident.split("."))
+            if p is not None:
+                reads.append((_segments(p), "cel", proven, set_))
+            continue
+        if chain.ident not in record.declarations:
+            continue
+        if chain.root in ("steps", "loops"):
+            (long if len(chain.path) >= 3 else short).add(chain.root)
+        reads.append((list(chain.path), "presence" if chain.presence else "cel", proven, set_))
+    return READS_EVERY if short - long else reads
+
+
+def _within(outer: Segs, path: Segs) -> bool:
+    return path[: len(outer)] == outer
+
+
+@dataclass(frozen=True)
+class _Use:
+    """One read of the step's, at its canonical segments. `strict`: a ref or template part without a default;
+    `defaulted`: one with a default, which replaces a missing or null value; `cel`: a CEL value read; `presence`: a
+    `has()` test, which reads only whether the value is there. `proven`: what its guards prove present (CEL);
+    `non_null`: what they prove not null, a condition for what it reads below, never for absence (`x != null` fails
+    where `x` is missing)."""
+
+    segs: Segs
+    r: Resolved
+    kind: Kind
+    proven: frozenset[Segs] = frozenset()
+    read: Segs = ()  # what it reads, before a list index (or each element, EVERY) cut it to `segs`
+    at: str = ""  # the field it's read at
+    non_null: frozenset[Segs] = frozenset()
+
+    @property
+    def needed(self) -> Segs:
+        """What must be there for it not to fail, as it reads (a list index or each element included): a `has()` test
+        needs only what holds the field it tests."""
+        read = self.read or self.segs
+        return read[:-1] if self.kind == "presence" else read
+
+    def tolerates_absence(self, entry: Segs) -> bool:
+        """Whether `entry` (this read or one outside it) may be absent: a default takes its place, a `has()` test of
+        it is false, a read of each element meets none, or a guard proves it, or something inside it on the way,
+        present wherever this is read."""
+        if self.kind == "defaulted" or (self.kind == "presence" and entry == self.segs):
+            return True
+        if EVERY in self.needed[len(entry) :]:
+            return True
+        return any(_within(entry, q) and _within(q, self.needed) for q in self.proven)
+
+    def needs_inside(self, entry: Segs) -> Hold | None:
+        """What it needs inside `entry`'s value when that's given: the rest of its path, held where what comes first is
+        there. A filter's read of each element needs nothing of an absent or empty list; a guard's read needs nothing
+        where what the guard proves present isn't."""
+        if self.kind == "defaulted" or len(self.needed) <= len(entry):
+            return None
+        rest = self.needed[len(entry) :]
+        given = rest.index(EVERY) if EVERY in rest else 0
+        for q in self.proven | self.non_null:
+            if len(q) > len(entry) and _within(entry, q) and _within(q, self.needed):
+                given = max(given, len(q) - len(entry))
+        return Hold(_pointer(rest), given) if given < len(rest) else None
+
+    def takes_null(self, place: Segs) -> bool:
+        """Whether a null at `place` (this read, or a place on its way) is fine for it: a default takes its place, or it
+        reads each element of a list at or below there, and a null one has none."""
+        return self.kind == "defaulted" or EVERY in self.needed[len(place) :]
+
+
+def _resolved(v: Any, site: Any, segs: Segs) -> Resolved | None:
+    if segs == ("vars",):  # the variables as a whole (`size(vars)`): every declared one, typed by its schema
+        return Resolved({"type": "object"}, False, v.vars_shape)
+    p = _ref_of(segs)
+    return v._resolve(site, p, report=False) if p is not None else None
+
+
+def _pointer(segs: Sequence[str | int]) -> str:
+    return "/" + "/".join("*" if x == EVERY else escape(x) for x in segs)
+
+
+def _entry(segs: Segs, uses: list[_Use]) -> SeedEntry:
+    """An outer read and the reads inside it, as one entry: the strictest use wins (§5.2)."""
+    own = [u for u in uses if u.segs == segs]
+    r = own[0].r
+    types = json_types(r.schema)
+    inner: dict[str, Mapping[str, Any] | None] = {}
+    null_ok: set[str] = set()
+    through: dict[Segs, list[_Use]] = {}  # each place inside the value a use reads through, list indexes too
+    for u in uses:
+        rel = u.segs[len(segs) :]
+        if rel:
+            inner.setdefault(_pointer(rel), u.r.schema)
+            if u.r.nullable:
+                null_ok.add(_pointer(rel))
+        read = u.read[len(segs) :]
+        for k in range(1, len(read) + 1):
+            through.setdefault(read[:k], []).append(u)
+    null_ok |= {_pointer(place) for place, by in through.items() if all(u.takes_null((*segs, *place)) for u in by)}
+    return SeedEntry(
+        pointer=_pointer(segs),
+        types=tuple(sorted(types)) if types is not None and types <= JSON_TYPES else (),
+        required=not all(u.tolerates_absence(segs) for u in uses),
+        nullable=r.nullable or all(u.takes_null(segs) for u in uses),
+        sensitive=r.taint.tainted,
+        holds=tuple(sorted({h for u in uses if (h := u.needs_inside(segs)) is not None})),
+        schema=r.schema,
+        inner=tuple(sorted(inner.items())),
+        null_ok=tuple(sorted(null_ok)),
+    )
+
+
+def contract(graph: Any, ctx: ValidationContext, node: uuid.UUID) -> SeedContract:
+    a = analyze(graph, ctx)
+    return contract_of(a, node)
+
+
+def contract_of(a: Analysis, node: uuid.UUID) -> SeedContract:
+    if a.structure is None or a.validator is None:
+        return SeedContract(refused=NO_ANALYSIS)
+    s, v = a.structure, a.validator
+    if node not in s.nodes:
+        return SeedContract(refused=NO_STEP)
+    spec = s.specs[node]
+    if not is_target(spec.ref, spec.kind == "control"):
+        return SeedContract(refused=NOT_ALONE)
+    records = {r.field: r for r in v.expressions if r.node == str(node)}
+    config = {pointer_str(pointer): value for pointer, value in iter_values(s.nodes[node].config)}
+    element = _element_of(config.get("/items"), records.get("/items")) if spec.ref == C.FILTER else None
+    computed = False  # a filter's predicate reads elements of a list its items compute
+    found: list[tuple[list[str | int], str, Kind, frozenset[Segs], frozenset[Segs]]] = []  # each read, where it's read
+    for at, value in config.items():
+        per_element = spec.ref == C.FILTER and at.startswith("/predicate")
+        none: frozenset[Segs] = frozenset()
+        reads: list[Read] = []
+        if isinstance(value, RefValue):
+            reads.append((_segments(value.path), "defaulted" if value.has_default else "strict", none, none))
+        elif isinstance(value, TemplateValue):
+            reads += [(_segments(part.path), "strict" if part.default is None else "defaulted", none, none)
+                      for part in value.parts if isinstance(part, TemplateRef)]  # fmt: skip
+        elif isinstance(value, CelValue) and at in records:
+            cel = _cel_reads(records[at])
+            if isinstance(cel, str):
+                return SeedContract(refused=cel)
+            reads += cel
+        for path, kind, proven, set_ in reads:
+            if path[0] == "run" or (per_element and path[0] == "index"):
+                continue
+            if per_element and path[0] == "item":  # each element of the filtered list, or a list computed
+                if element is None:  # what it needs can't be traced to a seed: the items' sources keep `required`
+                    strict = _Use(("item",), _ANY, kind, proven, tuple(path), non_null=set_).needs_inside(("item",))
+                    computed = computed or strict is not None
+                    continue
+                path = [*element, EVERY, *path[1:]]
+                proven = frozenset((*element, EVERY, *q[1:]) if q[:1] == ("item",) else q for q in proven)
+                set_ = frozenset((*element, EVERY, *q[1:]) if q[:1] == ("item",) else q for q in set_)
+            found.append((path, at, kind, proven, set_))
+    innermost = s.region_of[node]
+    key = s.nodes[innermost].key if innermost is not None and s.specs[innermost].ref == C.LOOP else None
+    aliases = {f"/loops/{escape(key)}/{name}": f"/{name}" for name in ("item", "index")} if key is not None else {}
+
+    def unaliased(path: Sequence[str | int]) -> Segs:
+        if key is not None and tuple(path[:2]) == ("loops", key) and len(path) >= 3:
+            return (str(path[2]), *path[3:])  # the innermost frame's alias
+        return tuple(path)
+
+    def canonical(path: Sequence[str | int]) -> Segs:
+        return tuple(_cut(list(unaliased(path))))
+
+    uses: list[_Use] = []
+    for segments, at, kind, proven, set_ in found:
+        segs = canonical(segments)
+        r = _resolved(v, site_of(s, node, at), segs)
+        if r is None:
+            return SeedContract(refused=NO_ANALYSIS)
+        uses.append(_Use(segs, r, kind, frozenset(unaliased(q) for q in proven), unaliased(segments), at,
+                         frozenset(unaliased(q) for q in set_)))  # fmt: skip
+    keeps = {u.segs for u in uses if u.at == "/items"} if computed else set()
+    outer: list[Segs] = []
+    for segs in sorted({u.segs for u in uses}, key=len):
+        if not any(_within(o, segs) for o in outer):
+            outer.append(segs)
+    entries = [_entry(o, [u for u in uses if _within(o, u.segs)]) for o in outer]
+    entries = [dataclasses.replace(e, keeps_required=True) if any(_within(o, k) for k in keeps) else e
+               for o, e in zip(outer, entries, strict=True)]  # fmt: skip
+    return SeedContract(tuple(sorted(entries, key=lambda e: e.pointer)), aliases)
+
+
+def _element_of(items: Any, record: ExpressionRecord | None) -> list[str | int] | None:
+    """What a filter's `item` is an element of, when its items are a path (a ref, or a CEL value that's only a path):
+    the predicate's reads then bind each element of that list. None when the items are computed."""
+    if isinstance(items, RefValue):
+        return _segments(items.path)
+    if not isinstance(items, CelValue) or record is None:
+        return None
+    try:
+        checked = runtime.compile_checked(record.expr, record.declarations).checked
+    except runtime.CompileError:
+        return None
+    chains = ast.chains(checked.expr)
+    if len(chains) != 1 or chains[0].presence or chains[0].expr_id != checked.expr.id:
+        return None
+    p = _ref_of(chains[0].ident.split(".") if "." in chains[0].ident else chains[0].path)
+    return _segments(p) if p is not None else None
+
+
+def _json_type(value: Any) -> str:
+    if value is None:
+        return "null"
+    if isinstance(value, bool):
+        return "boolean"
+    if isinstance(value, int):
+        return "integer"
+    if isinstance(value, float):
+        return "number"
+    if isinstance(value, str):
+        return "string"
+    return "array" if isinstance(value, list) else "object"
+
+
+_ABSENT = object()
+
+
+def _get(value: Any, pointer: str) -> Any:
+    """What `pointer` (relative, "/a/b") holds in `value`, or _ABSENT."""
+    for raw in pointer.split("/")[1:]:
+        seg = raw.replace("~1", "/").replace("~0", "~")
+        if not isinstance(value, Mapping) or seg not in value:
+            return _ABSENT
+        value = value[seg]
+    return value
+
+
+def _lacks(value: Any, hold: Hold) -> bool:
+    """Whether `value` breaks `hold`: a segment missing past its condition. One missing within the condition, or a
+    list with no element where it says `*`, needs nothing; a list index is followed as one."""
+    return _lacking(value, hold.pointer.split("/")[1:], hold.given)
+
+
+def _lacking(value: Any, segs: list[str], given: int) -> bool:
+    for i, raw in enumerate(segs):
+        if raw == "*":
+            if not isinstance(value, list):
+                return False  # not a list: its type is the schema's to refuse
+            return any(_lacking(element, segs[i + 1 :], max(0, given - i - 1)) for element in value)
+        found: Any = _ABSENT
+        if isinstance(value, Mapping):
+            found = value.get(raw.replace("~1", "/").replace("~0", "~"), _ABSENT)
+        elif isinstance(value, list) and raw.isdigit():
+            found = value[int(raw)] if int(raw) < len(value) else _ABSENT
+        if found is _ABSENT or (found is None and i < len(segs) - 1):  # nothing there, or nothing to go into
+            return i >= given
+        value = found
+    return False
+
+
+def _matches(place: str, patterns: Sequence[str]) -> bool:
+    """Whether `place` (a pointer) is one of `patterns`, a `*` in a pattern standing for any list index."""
+    parts = place.split("/")
+    for pattern in patterns:
+        expected = pattern.split("/")
+        if len(expected) == len(parts) and all(
+            e == p or (e == "*" and p.isdigit()) for e, p in zip(expected, parts, strict=True)
+        ):
+            return True
+    return False
+
+
+PRESENCE = frozenset({"required", "dependentRequired"})  # where they oblige: §5.2 takes presence from the uses
+
+
+def _excused(e: Any, null_ok: Sequence[str], at: str, presence: bool = True) -> bool:
+    """Whether a schema error is none for a seed: a presence the schema obliges (its uses decide, unless `presence`
+    is off), or a null at a place the uses take one. A choice (`anyOf`, `oneOf`) passes when a branch has nothing left
+    once these are excused: what was excused stands for a value the run supplies, which picks its own branch. `not`
+    and `if` keep their own meaning, since their errors are never these."""
+    if (presence and e.validator in PRESENCE) or (
+        e.instance is None and _matches(at + pointer_str(tuple(e.absolute_path)), null_ok)
+    ):
+        return True
+    if e.validator in ("anyOf", "oneOf") and e.context:
+        branches: dict[Any, list[Any]] = {}
+        for sub in e.context:
+            branches.setdefault(sub.relative_schema_path[0], []).append(sub)
+        return any(all(_excused(sub, null_ok, at, presence) for sub in errors) for errors in branches.values())
+    return False
+
+
+def _schema_problem(
+    schema: Mapping[str, Any] | None, value: Any, null_ok: Sequence[str], at: str = "", presence: bool = True
+) -> str | None:
+    """The first way `value` breaks `schema`, as it stands, that the uses don't excuse; worded with where (the
+    validator's own words, `explain`)."""
+    if schema is None:
+        return None
+    errors = Draft202012Validator(schema).iter_errors(value)
+    for e in sorted(errors, key=lambda e: str(list(e.absolute_path))):
+        if _excused(e, null_ok, at, presence):
+            continue
+        where = at + pointer_str(tuple(e.absolute_path))
+        return f"At {where}: {explain(e)}" if where else explain(e)
+    return None
+
+
+def _invalid(e: SeedEntry, value: Any) -> str | None:
+    """Why a non-null `value` doesn't fit `e`: its type, a path a read inside needs, its schema, or a read inside's."""
+    kind = _json_type(value)
+    if e.types and not (kind in e.types or (kind == "integer" and "number" in e.types)):  # a whole number is a number
+        return f"This value must be {' or '.join(e.types)}."
+    missing = [h.text for h in e.holds if _lacks(value, h)]
+    if missing:
+        return f"This value must hold {', '.join(missing)}."
+    excuse = not e.keeps_required
+    found = _schema_problem(e.schema, value, e.null_ok, presence=excuse)
+    for at, schema in e.inner:
+        if found is not None:
+            break
+        inside = _get(value, at)
+        if inside is not _ABSENT:
+            found = _schema_problem(schema, inside, e.null_ok, at, presence=excuse)
+    return found
+
+
+def _alias_of(aliases: Mapping[str, str], pointer: str) -> str | None:
+    """The canonical pointer for an alias, or for a path below one."""
+    for alias, canonical in aliases.items():
+        if pointer == alias or pointer.startswith(alias + "/"):
+            return canonical + pointer[len(alias) :]
+    return None
+
+
+def check(c: SeedContract, values: Mapping[str, Any], absent: Sequence[str]) -> list[SeedProblem]:
+    """The seeds against the contract (the simulation design §5.2): every entry in exactly one of `values` and
+    `absent`; absence only where optional, null only where nullable; each value fitting its schema, holding what a
+    read inside it needs; no pointer the contract doesn't list. Problems in pointer order."""
+    found: list[SeedProblem] = []
+    by_pointer = {e.pointer: e for e in c.entries}
+    for p in sorted({*values, *absent}):
+        canonical = _alias_of(c.aliases, p)
+        if canonical is not None:
+            found.append(SeedProblem(SEED_ALIAS, p, f"Give this value at {canonical}: it's the same one."))
+        elif p not in by_pointer:
+            found.append(SeedProblem(SEED_UNKNOWN, p, "This step doesn't read this value."))
+    for e in c.entries:
+        given, gone = e.pointer in values, e.pointer in absent
+        if given and gone:
+            found.append(SeedProblem(SEED_INVALID, e.pointer, "Give a value or leave it absent, not both."))
+        elif gone and e.required:
+            found.append(SeedProblem(SEED_MISSING, e.pointer, "This value can't be absent: the step reads it."))
+        elif not given and not gone:
+            found.append(SeedProblem(SEED_MISSING, e.pointer, "Give this value, or leave it absent if it may be."))
+        elif given and values[e.pointer] is None:
+            if not e.nullable:
+                found.append(SeedProblem(SEED_INVALID, e.pointer, "This value can't be null."))
+        elif given:
+            why = _invalid(e, values[e.pointer])
+            if why is not None:
+                found.append(SeedProblem(SEED_INVALID, e.pointer, why))
+    return sorted(found, key=lambda pr: (pr.pointer, pr.code))
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 74 passed. `of()` asserts each test's draft validates without an error,
so every obligation is the one a validated draft gets.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/engine/graph/seeds.py backend/tests/engine/graph/test_seeds.py
git commit -m "feat(engine): a single step's seed contract (S2, 4d-1 §5.2)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: A single step runs alone, from its seeds

**Spec:** §5.3, §5.4.

**Files:**
- Create: `backend/src/dewpoint/engine/runtime/seeds.py`
- Modify: `backend/src/dewpoint/engine/runtime/activities.py` (`RunInput.target_step_id`)
- Modify: `backend/src/dewpoint/engine/runtime/scheduler.py` (`target`, `start_target`, `fail`)
- Modify: `backend/src/dewpoint/engine/runtime/execution.py` (`seeds`, `_view`, `_values`, `_seeded`, `_drain_due`)
- Modify: `backend/src/dewpoint/engine/runtime/workflow.py` (the guards, `_fresh`, outputs and handler skipped)
- Modify: `backend/src/dewpoint/engine/cel/bind.py` (`ScopeView.framed`, `roots`)
- Modify: `backend/src/dewpoint/engine/runtime/resolve.py` (`_base`: `item` when framed, `vars` through a claim)
- Create: `backend/tests/apps/worker/test_run_graph_seeded.py`, `backend/tests/engine/runtime/test_seeds.py`
- Modify: `backend/tests/engine/replay/scenarios.py` (`single_step`)
- Record: `backend/tests/engine/replay/dewpoint-0.1.0+abi8/single_step.json` (with the commit)

**Interfaces:**
- Consumes: Task 8's `is_target`; the harness's `start(..., target_step_id=…)`, which passes `RunInput` fields.
- Produces:
  - `RunInput.target_step_id: str | None = None`;
  - `Scheduler.target`, `Scheduler.start_target(step)`; `ScopeView.framed: bool = False`;
  - `engine.runtime.seeds`: `segments(pointer)`, `Seeds.of(trigger, innermost)`, `Seeds.view(run, item=None)`,
    `Seeds.covers(path)`, `read_paths`, `cel_paths`, and the codes `SEED_MISSING`, `SEEDED_LIVE_REFUSED`,
    `TARGET_INVALID`.

The run's input is the seeds, `{"values": {pointer: value}, "absent": [pointer]}`, carried as its trigger:
- **Guards, before anything runs.** It must simulate (`seeded_live_refused`), and its target must be a step of the
  version that may run alone (`target_invalid`).
- **One instance.** The scheduler instantiates only the target, in the root scope, with no edges, so nothing else
  has a row.
- **The scope.** The target's view is built from the seeds, and `run` from the run itself. An absent value's
  containers are kept (ruling 5). Inside a loop the view is framed: `item` is in scope with or without an index
  (ruling 14), and the innermost loop's frame is there even when `/item` is absent. Variables given whole, as one
  claim, are each read through it.
- **The guard on reads.** A read the seeds don't cover fails the attempt `seed_missing`; admission's check makes it
  unreachable.
- **Its end.** The run ends with the step: its failure is the run's, whatever its error policy. No declared output, no
  failure handler, no continue-as-new (ruling 6).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_seeded.py b/backend/tests/apps/worker/test_run_graph_seeded.py
new file mode 100644
--- /dev/null
+++ b/backend/tests/apps/worker/test_run_graph_seeded.py
@@ -0,0 +1,229 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A single-step run (S2; the simulation design §5.3–5.4): one step of a version runs alone, simulated, with the values
+it reads given by pointer. Nothing else is instantiated, no declared output is evaluated and no failure handler runs;
+the run binds `run` itself; a read the seeds don't cover fails `seed_missing`; a live start, or a target that can't
+run alone, is refused before anything runs."""
+
+import asyncio
+import uuid
+from typing import Any
+
+from temporalio.testing import WorkflowEnvironment
+
+from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run_id_of, start, start_version, workers
+from tests.support.graphs import G, cel, nid, ref
+
+ECHO, FAIL_N, IF, LOOP, TRANSFORM = "testkit.echo@1", "testkit.fail_n@1", "flow.if@1", "flow.loop@1", "flow.transform@1"
+SET, FILTER = "flow.set_variables@1", "flow.filter@1"
+
+
+def graph(**outputs: Any) -> G:
+    g = G()
+    g.settings = {
+        "input_schema": {
+            "type": "object",
+            "properties": {
+                "x": {"type": "integer"},
+                "count": {"type": "integer"},
+                "owner": {"type": "object", "properties": {"tag": {"type": "integer"}}, "additionalProperties": False},
+                "ns": {
+                    "type": "array",
+                    "items": {
+                        "type": "object",
+                        "properties": {"n": {"type": "integer"}},
+                        "required": ["n"],
+                        "additionalProperties": False,
+                    },
+                },
+            },
+            "required": ["x", "owner"],
+        },  # fmt: skip
+        **({"outputs": outputs} if outputs else {}),
+    }
+    return g
+
+
+async def alone(env: WorkflowEnvironment, store: MemoryStore, g: G, target: str, seeds: dict[str, Any],
+                mode: str = "simulate") -> tuple[Any, str]:  # fmt: skip
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, seeds, mode=mode, target_step_id=str(nid(target)))
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    return result, run_id_of(handle)
+
+
+async def test_one_step_runs_alone_with_its_seeds(env: WorkflowEnvironment) -> None:
+    """`b` alone: `a` and `c` are never instantiated, and the outputs (which read `c`) aren't evaluated."""
+    store = MemoryStore()
+    g = graph(last=ref("steps.c.output.value")).node("a", ECHO, {"value": 1})
+    g.node("b", ECHO, {"value": ref("steps.a.output.value")}).node("c", ECHO, {"value": 3}).edge("a", "b").edge(
+        "b", "c"
+    )
+    result, run_id = await alone(env, store, g, "b", {"values": {"/steps/a/output/value": 5}, "absent": []})
+    assert (result.status, result.outputs) == ("succeeded", None)
+    [row] = store.steps(run_id)
+    assert (row.node_key, row.iteration_key, row.status, row.outcome) == ("b", "", "succeeded", "simulated")
+    assert row.input_preview == {"value": 5}
+
+
+async def test_the_run_binds_its_own_fields_without_seeds(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    fields = {"id": cel("run.id"), "started": ref("run.started_at"), "now": cel("run.now")}
+    g = graph().node("t", TRANSFORM, {"fields": fields})
+    result, run_id = await alone(env, store, g, "t", {"values": {}, "absent": []})
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    assert row.output_preview["id"] == run_id and row.output_preview["started"] and row.output_preview["now"]
+
+
+async def test_an_absent_seed_leaves_its_container_in_place(env: WorkflowEnvironment) -> None:
+    """`/trigger/owner/tag` absent: `owner` is still there (the schema says so), so `has()` is false, not an error."""
+    store = MemoryStore()
+    g = graph().node("t", TRANSFORM, {"fields": {"tagged": cel("has(trigger.owner.tag) ? 1 : 0")}})
+    result, run_id = await alone(env, store, g, "t", {"values": {}, "absent": ["/trigger/owner/tag"]})
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    assert row.output_preview == {"tagged": 0}
+
+
+async def test_a_live_single_step_is_refused_before_anything_runs(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("b", ECHO, {"value": 1})
+    result, run_id = await alone(env, store, g, "b", {"values": {}, "absent": []}, mode="live")
+    assert (result.status, result.error["code"]) == ("failed", "seeded_live_refused")
+    assert store.steps(run_id) == []
+
+
+async def test_a_target_that_cant_run_alone_is_refused(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("l", LOOP, {"items": [1]}).node("x", ECHO, {"value": 1}).edge("l", "x", "body")
+    result, run_id = await alone(env, store, g, "l", {"values": {}, "absent": []})
+    assert (result.status, result.error["code"]) == ("failed", "target_invalid")
+    assert store.steps(run_id) == []
+
+
+async def test_a_read_the_seeds_dont_cover_fails_seed_missing(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("a", ECHO, {"value": 1}).node("b", ECHO, {"value": ref("steps.a.output.value")}).edge("a", "b")
+    result, run_id = await alone(env, store, g, "b", {"values": {}, "absent": []})
+    assert (result.status, result.error["code"]) == ("failed", "seed_missing")
+    [row] = store.steps(run_id)
+    assert (row.node_key, row.status, row.error_code) == ("b", "failed", "seed_missing")
+
+
+async def test_an_absent_seed_takes_the_references_default(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("b", ECHO, {"value": ref("trigger.count", default=9)})  # an echo's strings are claimed: a number
+    result, run_id = await alone(env, store, g, "b", {"values": {}, "absent": ["/trigger/count"]})
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    assert row.input_preview == {"value": 9}
+
+
+async def test_a_loop_contained_step_reads_its_frame_from_item_and_index(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("l", LOOP, {"items": [1, 2]})
+    g.node("x", ECHO, {"value": {"i": ref("item"), "n": ref("loops.l.index")}}).edge("l", "x", "body")
+    result, run_id = await alone(env, store, g, "x", {"values": {"/item": 2, "/index": 3}, "absent": []})
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    assert (row.iteration_key, row.input_preview) == ("", {"value": {"i": 2, "n": 3}})
+
+
+async def test_a_loop_contained_step_that_reads_only_its_item_needs_no_index(env: WorkflowEnvironment) -> None:
+    """The frame is there whether or not its index is read: `/item/n` alone, through a ref and through CEL."""
+    store = MemoryStore()
+    g = graph().node("l", LOOP, {"items": ref("trigger.ns", default=[])})
+    g.node("t", TRANSFORM, {"fields": {"a": ref("item.n"), "b": cel("item.n + 1")}}).edge("l", "t", "body")
+    result, run_id = await alone(env, store, g, "t", {"values": {"/item/n": 7}, "absent": []})
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    assert row.output_preview == {"a": 7, "b": 8}
+
+
+async def test_the_variables_seeded_whole_as_one_claim_are_each_read_through_it(env: WorkflowEnvironment) -> None:
+    """`size(vars)` beside a sensitive `vars.n`: one sensitive `/vars` entry, which admission claims whole. A
+    variable is read through that claim, as through any claimed value."""
+    store = MemoryStore()
+    g = graph()
+    g.settings["vars_schema"] = {"type": "object", "properties": {"n": {"type": "integer", "x-sensitive": True}}}
+    g.node("s", SET, {"assignments": {"n": ref("trigger.x")}})
+    g.node("t", TRANSFORM, {"fields": {"count": cel("size(vars)"), "n": ref("vars.n")}}).edge("s", "t")
+    run_id = str(uuid.uuid4())
+    seeds = {"values": {"/vars": store.claim({"n": 5}, owner=run_id, tainted=True)}, "absent": []}
+    async with workers(env.client, store):
+        handle = await start_version(env.client, store.add(g), seeds, run_id=run_id, mode="simulate",
+                                     target_step_id=str(nid("t")))  # fmt: skip
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    counted = row.output_preview["count"]  # a result over sensitive data is claimed (engine 2b spec §4)
+    assert store.claims[counted["$claim"]].value == 1
+
+
+async def test_an_absent_item_leaves_its_loops_frame_in_place(env: WorkflowEnvironment) -> None:
+    """`/item` absent: the innermost loop's frame is still there, empty, so `has(loops.l.item)` is false."""
+    store = MemoryStore()
+    g = graph().node("l", LOOP, {"items": ref("trigger.ns", default=[])})
+    g.node("t", TRANSFORM, {"fields": {"v": cel("has(loops.l.item) ? 1 : 0")}}).edge("l", "t", "body")
+    result, run_id = await alone(env, store, g, "t", {"values": {}, "absent": ["/item"]})
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    assert row.output_preview == {"v": 0}
+
+
+async def test_a_guarded_read_of_a_required_field_runs_with_it_absent(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("t", TRANSFORM, {"fields": {"v": cel("has(trigger.x) ? trigger.x : 0")}})
+    result, run_id = await alone(env, store, g, "t", {"values": {}, "absent": ["/trigger/x"]})
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    assert row.output_preview == {"v": 0}
+
+
+async def test_a_value_whose_inner_read_has_a_default_runs_without_it_or_with_null(env: WorkflowEnvironment) -> None:
+    """`owner` read whole and `owner.tag` with a default: `{}` and `{"tag": null}` both run, the default in place."""
+    store = MemoryStore()
+    fields = {"o": cel("size(trigger.owner)"), "t": ref("trigger.owner.tag", default=9)}
+    g = graph().node("t", TRANSFORM, {"fields": fields})
+    for owner, size in (({}, 0), ({"tag": None}, 1)):
+        result, run_id = await alone(env, store, g, "t", {"values": {"/trigger/owner": owner}, "absent": []})
+        assert result.status == "succeeded", result.error
+        [row] = store.steps(run_id)
+        assert row.output_preview == {"o": size, "t": 9}
+
+
+async def test_a_filter_alone_takes_elements_its_guarded_predicate_reads_nothing_of(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node(
+        "f", FILTER, {"items": ref("trigger.ns", default=[]), "predicate": cel("has(item.n) && item.n > 0")}
+    )
+    result, run_id = await alone(env, store, g, "f", {"values": {"/trigger/ns": [{}, {"n": 2}]}, "absent": []})
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    assert row.status == "succeeded"
+
+
+async def test_a_filter_alone_over_a_null_list_takes_its_items_default(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("f", FILTER, {"items": ref("trigger.ns", default=[]), "predicate": cel("item.n > 0")})
+    result, run_id = await alone(env, store, g, "f", {"values": {"/trigger/ns": None}, "absent": []})
+    assert result.status == "succeeded", result.error
+
+
+async def test_an_if_alone_records_its_port_and_nothing_downstream(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("c", IF, {"condition": cel("trigger.x > 5")}).node("y", ECHO, {"value": 1}).edge("c", "y", "true")
+    result, run_id = await alone(env, store, g, "c", {"values": {"/trigger/x": 7}, "absent": []})
+    assert result.status == "succeeded", result.error
+    [row] = store.steps(run_id)
+    assert (row.node_key, row.effect_preview) == ("c", {"port": "true"})
+
+
+async def test_a_failing_step_fails_its_run_whatever_its_error_policy(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph().node("f", FAIL_N, {"failures": 10}, on_error="continue")
+    g.nodes[0]["options"]["max_attempts"] = 1
+    result, run_id = await alone(env, store, g, "f", {"values": {}, "absent": []})
+    assert (result.status, result.error["code"]) == ("failed", "simulation_unavailable")  # it has no simulator
+    [row] = store.steps(run_id)
+    assert (row.status, row.outcome) == ("failed", "simulated")
diff --git a/backend/tests/engine/replay/scenarios.py b/backend/tests/engine/replay/scenarios.py
--- a/backend/tests/engine/replay/scenarios.py
+++ b/backend/tests/engine/replay/scenarios.py
@@ -6,8 +6,9 @@ error policy; variables and timers; stop, fail, simulation and the deadline; CEL
 batched loops, sub-flows, the failure handler, grants, continue-as-new and drain mode. 2a-3c turns local CEL on:
 expressions run in the workflow, with the yield-point timer, and the rest go to `cel.evaluate`. It also records a
 cancelled run and a version this build can't compile. 2b-4b's engine blockers add a value several binding sets share,
-claimed once (#26). Editor 4d-1a adds a simulated timer, not waited (the simulation design §4.2). A scenario that
-runs sub-flows builds its graph against the recorder's store, which publishes them first."""
+claimed once (#26). Editor 4d-1a adds a simulated timer, not waited, and a single step run alone with its seeds (the
+simulation design §4.2, §5). A scenario that runs sub-flows builds its graph against the recorder's store, which
+publishes them first."""
 
 from collections.abc import Callable
 from dataclasses import dataclass, field
@@ -16,7 +17,7 @@ from typing import Any
 from dewpoint.engine.graph.validate import ValidationContext, validate
 from tests.apps.worker.harness import CATALOG, EVALUATOR_ONLY, MemoryStore
 from tests.engine.cel.test_gate_cost import ADVERSARIAL
-from tests.support.graphs import G, cel, ref
+from tests.support.graphs import G, cel, nid, ref
 
 ECHO, IF, SWITCH, LOOP = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1"
 SCHEMA: dict[str, Any] = {
@@ -253,4 +254,12 @@ def scenarios() -> dict[str, Scenario]:
             _graph().node("d", "flow.delay@1", {"duration_s": 3_600}).node("a", ECHO, {"value": 1}).edge("d", "a"),
             options={"mode": "simulate"},
         ),
+        "single_step": Scenario(
+            _graph()
+            .node("a", ECHO, {"value": 1})
+            .node("b", ECHO, {"value": ref("steps.a.output.value")})
+            .edge("a", "b"),
+            trigger={"values": {"/steps/a/output/value": 5}, "absent": []},
+            options={"mode": "simulate", "target_step_id": str(nid("b"))},
+        ),
     }
diff --git a/backend/tests/engine/runtime/test_seeds.py b/backend/tests/engine/runtime/test_seeds.py
new file mode 100644
--- /dev/null
+++ b/backend/tests/engine/runtime/test_seeds.py
@@ -0,0 +1,44 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A single-step run's seeds (S2; the simulation design §5.3): the scope view built from them, and what they cover."""
+
+from dewpoint.engine.runtime.seeds import Seeds, segments
+
+
+def test_pointers_are_unescaped_segments() -> None:
+    assert segments("") == ()
+    assert segments("/steps/a~1b/output/x~0y") == ("steps", "a/b", "output", "x~y")
+
+
+def test_values_build_the_tree_an_outer_value_first() -> None:
+    s = Seeds.of({"values": {"/trigger/owner/name": "n", "/trigger/owner": {"tag": 1}}, "absent": []}, None)
+    assert s.trigger == {"owner": {"tag": 1, "name": "n"}}
+
+
+def test_an_absent_value_leaves_its_containers_in_place() -> None:
+    s = Seeds.of({"values": {}, "absent": ["/trigger/owner/tag", "/steps/a/output/x"]}, None)
+    view = s.view({"id": "r"})
+    assert s.trigger == {"owner": {}} and view.steps == {"a": {"output": {}}}
+
+
+def test_the_innermost_frame_is_item_and_index_and_its_loops_alias() -> None:
+    s = Seeds.of({"values": {"/item": {"mac": "m"}, "/index": 2}, "absent": []}, "l")
+    view = s.view({"id": "r"})
+    assert (view.item, view.index, view.loops["l"]) == ({"mac": "m"}, 2, {"item": {"mac": "m"}, "index": 2})
+    assert s.covers(("loops", "l", "item", "mac")) and not s.covers(("loops", "outer", "item"))
+
+
+def test_a_read_is_covered_by_a_given_or_an_absent_value_above_it() -> None:
+    s = Seeds.of({"values": {"/trigger/site": "HQ"}, "absent": ["/vars/n"]}, None)
+    assert s.covers(("trigger", "site")) and s.covers(("vars", "n", "deep"))
+    assert not s.covers(("trigger",)) and not s.covers(("steps", "a", "output"))
+
+
+def test_the_frame_is_there_without_its_index() -> None:
+    """A step that reads only its item gets the item's frame: `item` is in scope with no `index` given."""
+    view = Seeds.of({"values": {"/item/n": 1}, "absent": []}, "l").view({"id": "r"})
+    assert (view.framed, view.item, view.index) == (True, {"n": 1}, None)
+
+
+def test_an_absent_item_leaves_its_loops_frame_empty() -> None:
+    view = Seeds.of({"values": {}, "absent": ["/item"]}, "l").view({"id": "r"})
+    assert (view.loops, view.framed, view.item) == ({"l": {}}, True, None)
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/worker/test_run_graph_seeded.py tests/engine/runtime
tests/engine/cel tests/engine/replay`

Expected: FAIL, 18 failed, 636 passed, 1 skipped and 1 error:
- "RunInput.__init__() got an unexpected keyword argument 'target_step_id'" (the seventeen seeded runs);
- "No module named 'dewpoint.engine.runtime.seeds'";
- `single_step` isn't recorded.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/engine/cel/bind.py b/backend/src/dewpoint/engine/cel/bind.py
--- a/backend/src/dewpoint/engine/cel/bind.py
+++ b/backend/src/dewpoint/engine/cel/bind.py
@@ -34,6 +34,7 @@ class ScopeView:
     run: Mapping[str, str]  # id, started_at, now: RFC 3339 UTC strings
     item: Any = None  # the innermost loop's item, or the filter item in a predicate
     index: int | None = None
+    framed: bool = False  # an item in scope without its index: a single step's seeds give only what it reads (S2)
 
     def roots(self) -> dict[str, Any]:
         out: dict[str, Any] = {
@@ -43,8 +44,10 @@ class ScopeView:
             "loops": self.loops,
             "run": self.run,
         }
+        if self.framed or self.index is not None:
+            out["item"] = self.item
         if self.index is not None:
-            out.update(item=self.item, index=self.index)
+            out["index"] = self.index
         return out
 
 
diff --git a/backend/src/dewpoint/engine/runtime/activities.py b/backend/src/dewpoint/engine/runtime/activities.py
--- a/backend/src/dewpoint/engine/runtime/activities.py
+++ b/backend/src/dewpoint/engine/runtime/activities.py
@@ -81,6 +81,9 @@ class RunInput:
     checkpoint_events: int = CHECKPOINT_EVENTS
     drain_events: int = DRAIN_EVENTS
     iterations: int = 0  # a continued run: what it had used, readable even when its snapshot isn't
+    # a single-step run (S2; the simulation design §5.4): its one step, simulated; its `trigger` is then its seeds,
+    # `{"values": {pointer: value}, "absent": [pointer]}`, and `version_id` may name a draft snapshot
+    target_step_id: str | None = None
 
 
 @dataclass(frozen=True)
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -113,6 +113,7 @@ with workflow.unsafe.imports_passed_through():
         count,
         iteration_key,
     )
+    from dewpoint.engine.runtime.seeds import SEED_MISSING, Seeds, cel_paths, read_paths
     from dewpoint.engine.runtime.size import (
         BATCH_ITEM_TOO_LARGE,
         PAYLOAD_TOO_LARGE,
@@ -298,6 +299,7 @@ class Execution:
         self._finished: set[Instance] = set()
         self._effects: dict[Instance, dict[str, Any]] = {}
         self._not_waited: dict[Instance, Any] = {}  # a simulated timer's resolved config, for its row (§4.2)
+        self.seeds: Seeds | None = None  # a single-step run's (S2): its scope, in place of the scheduler's
         self._projects = 0
         self._timers: dict[Instance, datetime] = {}  # a timer step asleep -> its wake time
         self._resume: list[Instance] = []  # timer steps a snapshot carried over: they re-arm first
@@ -492,6 +494,8 @@ class Execution:
         is counted out, so a continued run never drains at once), or Temporal suggests continuing. The drive loop
         wakes for it too, so a drain begins at the first workflow task past the threshold, not at the next unit's
         end."""
+        if self.seeds is not None:  # a single step: its history is its attempts', and it never continues as new
+            return False
         info = workflow.info()
         return (
             info.get_current_history_length() >= self.drain_events
@@ -890,6 +894,8 @@ class Execution:
             "started_at": self.run_started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
             "now": workflow.now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
         }
+        if self.seeds is not None:  # a single step's scope is its seeds and the run (S2)
+            return self.seeds.view(run, item)
         variables = self.vars if variables is None else variables
         return resolve.view(self.sched, scope, trigger=self.trigger, variables=variables, run=run, item=item)
 
@@ -906,6 +912,8 @@ class Execution:
         values: dict[str, Any] = {}
         mode: str | None = None
         v = self._view(scope, variables=variables)
+        if self.seeds is not None and owner is not None:
+            self._seeded(owner, pairs)
         for pointer, value in pairs:
             if isinstance(value, RefValue):
                 values[pointer] = await self._ref(v, value, owner, scope)
@@ -939,6 +947,28 @@ class Execution:
                 values[pointer] = value.value
         return values, mode
 
+    def _seeded(self, owner: Step, pairs: list[tuple[str, Any]]) -> None:
+        """A single step reads only what its seeds cover (S2): a value given, or one left absent. Anything else is a
+        guard's failure, `seed_missing`, before any value is computed; admission's check makes it unreachable. The
+        run's own `run` is always there."""
+        seeds = self.seeds
+        if seeds is None:
+            return
+        for pointer, value in pairs:
+            if isinstance(value, RefValue):
+                paths = [read_paths(value.path)]
+            elif isinstance(value, TemplateValue):
+                paths = [read_paths(part.path) for part in value.parts if not isinstance(part, str)]
+            elif isinstance(value, CelValue):
+                paths = list(cel_paths(self.program.record(owner.id, pointer)))
+            else:
+                continue
+            for path in paths:
+                if path and path[0] != "run" and not seeds.covers(path):
+                    shown = ".".join(str(p) for p in path)
+                    message = f"`{shown}` has no seed: give it a value, or leave it absent."
+                    raise resolve.ValueFailure(SEED_MISSING, message)
+
     # --- handles (engine 2b spec §3.2–3.3): never read here, resolved in activities ------------------------------
 
     async def _ref(self, v: Any, value: RefValue, owner: Step | None, scope: ScopeKey) -> Any:
diff --git a/backend/src/dewpoint/engine/runtime/resolve.py b/backend/src/dewpoint/engine/runtime/resolve.py
--- a/backend/src/dewpoint/engine/runtime/resolve.py
+++ b/backend/src/dewpoint/engine/runtime/resolve.py
@@ -77,9 +77,14 @@ def _base(v: ScopeView, path: RefPath) -> Any:
             return claimed.extend(str(path.section)).to_json()
         return entry.get(str(path.section), MISSING) if isinstance(entry, Mapping) else MISSING
     if path.root == "vars":
+        claimed = ClaimRef.of(v.vars)
+        if claimed is not None:  # the variables given whole, as one claim (a single step's seeds, S2): read by handle
+            return claimed.extend(str(path.name)).to_json()
         return v.vars.get(str(path.name), MISSING)
-    if path.root in ("item", "index"):
-        return MISSING if v.index is None else (v.item if path.root == "item" else v.index)
+    if path.root == "item":
+        return v.item if v.framed or v.index is not None else MISSING
+    if path.root == "index":
+        return MISSING if v.index is None else v.index
     if path.root == "loops":
         loop = v.loops.get(str(path.name))
         return loop.get(str(path.section), MISSING) if loop is not None else MISSING
diff --git a/backend/src/dewpoint/engine/runtime/scheduler.py b/backend/src/dewpoint/engine/runtime/scheduler.py
--- a/backend/src/dewpoint/engine/runtime/scheduler.py
+++ b/backend/src/dewpoint/engine/runtime/scheduler.py
@@ -530,6 +530,7 @@ class Scheduler:
         self.scopes: dict[ScopeKey, Scope] = {}
         self.loops: dict[Instance, LoopRun] = {}
         self.ended: RunEnd | None = None
+        self.target: uuid.UUID | None = None  # a single-step run's one step (S2)
         self.batch_loop: Instance | None = None  # a batch child: the loop whose slice it runs
         self.outcome: BatchOutcome | None = None  # a batch child: its slice's result, once it's done
         self._ready: list[Instance] = []
@@ -596,6 +597,15 @@ class Scheduler:
     def start(self) -> None:
         self._open_scope((), None)
 
+    @_then_wake
+    def start_target(self, step: uuid.UUID) -> None:
+        """A single-step run (S2; the simulation design §5.3): `step` alone, in the root scope, with no edges, so
+        nothing else is ever instantiated. The run ends with it: its failure fails the run, whatever its `on_error`."""
+        self.target = step
+        scope = Scope((), self.program.steps[step].region, {step: NodeState.WAITING}, {}, {})
+        self.scopes[()] = scope
+        self._check_ready(scope, step)
+
     def start_batch(
         self,
         loop_step: uuid.UUID,
@@ -782,6 +792,9 @@ class Scheduler:
             return
         scope.nodes[step.id] = NodeState.FAILED
         self._settled.append((inst, {"error": failure.to_json()}))
+        if self.target is not None:  # a single step's failure is its run's (S2)
+            self._fail_scope(scope, failure)
+            return
         if step.on_error == "port":
             scope.results[step.key] = {"error": failure.to_json()}
             self._live += size(scope.results[step.key])
diff --git a/backend/src/dewpoint/engine/runtime/seeds.py b/backend/src/dewpoint/engine/runtime/seeds.py
new file mode 100644
--- /dev/null
+++ b/backend/src/dewpoint/engine/runtime/seeds.py
@@ -0,0 +1,115 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A single-step run's seeds (S2; the simulation design §5.3): the values its one step reads, given by pointer
+(`{"values": {pointer: value}, "absent": [pointer]}`, the run's trigger), and the scope view built from them in place
+of the scheduler's. The run binds `run` itself. A loop-contained step's innermost frame is `/item` and `/index`, which
+its `loops.<key>` reads too. Nothing else is in scope: a read the seeds don't cover is a guard's failure
+(`seed_missing`), which admission's check makes unreachable."""
+
+from collections.abc import Mapping, Sequence
+from dataclasses import dataclass, field
+from typing import Any
+
+from dewpoint.engine.cel.bind import ScopeView
+from dewpoint.engine.cel.record import ExpressionRecord
+from dewpoint.engine.graph.values import RefPath
+
+SEED_MISSING = "seed_missing"
+SEEDED_LIVE_REFUSED = "seeded_live_refused"
+TARGET_INVALID = "target_invalid"
+
+
+def segments(pointer: str) -> tuple[str, ...]:
+    """A JSON pointer's segments (RFC 6901), unescaped."""
+    if pointer == "":
+        return ()
+    if not pointer.startswith("/"):
+        raise ValueError(f"not a JSON pointer: {pointer!r}")
+    return tuple(s.replace("~1", "/").replace("~0", "~") for s in pointer[1:].split("/"))
+
+
+def _put(tree: dict[str, Any], path: Sequence[str], value: Any) -> None:
+    for seg in path[:-1]:
+        nxt = tree.get(seg)
+        if not isinstance(nxt, dict):
+            nxt = tree[seg] = {}
+        tree = nxt
+    tree[path[-1]] = value
+
+
+def _hollow(tree: dict[str, Any], path: Sequence[str]) -> None:
+    """The containers above an absent value: it's absent from them, they're there (`has()` is false, not an error)."""
+    for seg in path:
+        nxt = tree.setdefault(seg, {})
+        if not isinstance(nxt, dict):
+            return
+        tree = nxt
+
+
+@dataclass(frozen=True)
+class Seeds:
+    values: Mapping[str, Any]
+    absent: tuple[str, ...]
+    innermost: str | None = None  # the key of the loop around the step, if any: its frame is `/item`, `/index`
+    tree: dict[str, Any] = field(default_factory=dict, compare=False)
+
+    @classmethod
+    def of(cls, trigger: Mapping[str, Any], innermost: str | None) -> "Seeds":
+        values = dict(trigger.get("values") or {})
+        tree: dict[str, Any] = {}
+        for pointer in sorted(values, key=lambda p: len(segments(p))):  # an outer value first, an inner one on it
+            path = segments(pointer)
+            if path:
+                _put(tree, path, values[pointer])
+        absent = tuple(trigger.get("absent") or ())
+        for pointer in absent:
+            _hollow(tree, segments(pointer)[:-1])
+        return cls(values, absent, innermost, tree)
+
+    @property
+    def trigger(self) -> dict[str, Any]:
+        found = self.tree.get("trigger", {})
+        return found if isinstance(found, dict) else {}
+
+    def view(self, run: Mapping[str, str], item: tuple[Any, int] | None = None) -> ScopeView:
+        """The step's scope: its seeds, the run's own `run`, and a filter's element when `item` is given."""
+        loops = {k: dict(v) for k, v in (self.tree.get("loops") or {}).items() if isinstance(v, dict)}
+        if self.innermost is not None:  # its frame, with what's given of it: empty when `/item` is absent
+            loops[self.innermost] = {k: self.tree[k] for k in ("item", "index") if k in self.tree}
+        value: Any = self.tree.get("item")
+        index: Any = self.tree.get("index")
+        if item is not None:
+            value, index = item
+        steps = self.tree.get("steps") or {}
+        variables = self.tree.get("vars") or {}
+        return ScopeView(trigger=self.trigger, steps=steps, vars=variables, loops=loops, run=run, item=value,
+                         index=index, framed=self.innermost is not None or item is not None)  # fmt: skip
+
+    def covers(self, path: Sequence[str | int]) -> bool:
+        """Whether a read of `path` (root first) is within a given or an absent value."""
+        path = tuple(str(p) for p in path)
+        if self.innermost is not None and path[:2] == ("loops", self.innermost) and len(path) >= 3:
+            path = path[2:]  # the innermost frame's alias
+        for pointer in (*self.values, *self.absent):
+            seg = segments(pointer)
+            if path[: len(seg)] == seg:
+                return True
+        return False
+
+
+def read_paths(p: RefPath) -> tuple[str | int, ...]:
+    """A reference's path, root first, as `covers` reads it."""
+    if p.root in ("steps", "loops"):
+        return (p.root, str(p.name), str(p.section), *p.rest)
+    if p.root == "vars":
+        return ("vars", *([str(p.name)] if p.name is not None else []), *p.rest)
+    return (p.root, *p.rest)
+
+
+def cel_paths(record: ExpressionRecord) -> list[tuple[str, ...]]:
+    """What a CEL value reads that must be there: its typed paths, and its projections but presence tests."""
+    out = [tuple(i.split(".")) for i in record.idents if "." in i]
+    roots = {i for i in record.idents if "." not in i}
+    out += [tuple(pr.path) for pr in record.projections if not pr.presence and pr.path and pr.path[0] in roots]
+    covered = {pr.path[0] for pr in record.projections if pr.path}
+    out += [(r,) for r in roots if r not in covered]
+    return out
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -19,11 +19,13 @@ from temporalio.common import VersioningBehavior
 from temporalio.exceptions import ApplicationError, ChildWorkflowError
 
 with workflow.unsafe.imports_passed_through():
+    from dewpoint.engine.graph.seeds import is_target
     from dewpoint.engine.graph.values import iter_values, pointer_str
     from dewpoint.engine.handles import contains_marker
     from dewpoint.engine.runtime.activities import (
         FAILURE_HANDLER,
         LOAD_VERSION,
+        SIMULATE,
         SUBFLOW,
         BatchInput,
         BatchResult,
@@ -68,6 +70,7 @@ with workflow.unsafe.imports_passed_through():
         RunEnd,
         Scheduler,
     )
+    from dewpoint.engine.runtime.seeds import SEEDED_LIVE_REFUSED, TARGET_INVALID, Seeds
     from dewpoint.engine.runtime.size import (
         BATCH_RESULTS_TOO_LARGE,
         BATCH_SNAPSHOT_TOO_LARGE,
@@ -189,12 +192,22 @@ class RunGraph(Execution):
             workflow.logger.error("run_version_unusable", extra=_bug(e))
             message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
             return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, message)), start.iterations)
+        target: uuid.UUID | None = None
+        if start.target_step_id is not None:  # a single step (S2): checked again here, before anything runs
+            refused = self._target_refused(start, program)
+            if refused is not None:
+                return await self._end_early(RunEnd("failed", refused), start.iterations)
+            target = uuid.UUID(start.target_step_id)
+            region = program.steps[target].region
+            innermost = program.steps[region].key if region is not None else None
+            self.seeds = Seeds.of(start.trigger, innermost)
+            self.trigger = self.seeds.trigger
         outputs: dict[str, Any] | None = None
         try:
             if snapshot is not None:
                 await self._restore(program, snapshot)
             else:
-                self._fresh(program)
+                self._fresh(program, target)
             if await self._drive() == CONTINUE:
                 await self._flush()
                 continued = replace(start, snapshot=await self._snapshot(), iterations=self.sched.iterations)
@@ -204,7 +217,7 @@ class RunGraph(Execution):
                 # engine 2b spec §5.3: too large to carry on, the run ends here, cleanly (2b-1b bounds the state)
                 self.sched.end(RunEnd("failed", Failure(SNAPSHOT_TOO_LARGE, RUN_SNAPSHOT_TOO_LARGE)))
             end = self.sched.ended or RunEnd("failed", Failure("error", "The run ended without a result."))
-            if end.status == "succeeded":
+            if end.status == "succeeded" and target is None:  # a single step has no declared outputs (S2)
                 end, outputs = await self._outputs_by(end)
             if outputs is not None and not self._returnable(outputs):  # checked here, where the result is made
                 end, outputs = RunEnd("failed", Failure(PAYLOAD_TOO_LARGE, OUTPUTS_TOO_LARGE)), None
@@ -228,21 +241,38 @@ class RunGraph(Execution):
             counted = {"iterations": _counted(self, start.iterations)}  # its end shows no zero for work it used
             raise ApplicationError(message, counted, type=INTERNAL_ERROR, non_retryable=True) from None
         ended = workflow.now()  # the end is decided: whatever follows, it stands
-        pin = self._handler_pin(data) if end.status in HANDLED else None
+        pin = self._handler_pin(data) if end.status in HANDLED and target is None else None  # none for one step
         if pin is not None and not await self._project_end(None):  # its rows land; its end waits for the handler
             await self._failure_handler(pin, data, self._end_error(end))  # (a cancel meanwhile: no handler)
         return await self._finish(end, outputs, ended)
 
-    def _fresh(self, program: Program) -> None:
+    def _target_refused(self, start: RunInput, program: Program) -> Failure | None:
+        """A single-step run's guards (S2; the simulation design §5.4), as admission checks them: it simulates, and its
+        target is a step of the version that may run alone."""
+        if start.mode != SIMULATE:
+            return Failure(SEEDED_LIVE_REFUSED, "A single step runs only as a simulation.")
+        try:
+            step = program.steps.get(uuid.UUID(str(start.target_step_id)))
+        except ValueError:
+            step = None
+        if step is None or not is_target(step.ref, step.control):
+            return Failure(TARGET_INVALID, "This step isn't one that can run alone.")
+        return None
+
+    def _fresh(self, program: Program, target: uuid.UUID | None = None) -> None:
         """A new run's state: its budget (the cap, or what its parent granted) and its variables. Its sensitive values
-        are handles already (engine 2b spec §3.5): nothing here holds one to learn."""
+        are handles already (engine 2b spec §3.5): nothing here holds one to learn. A single-step run starts its one
+        step alone (S2)."""
         self.program = program
         parent = self.parent
         budget = Budget(ITERATION_CAP, root=True) if parent is None else Budget(parent.grant, root=False)
         self.sched = Scheduler(program, budget=budget, prefix=workflow.info().workflow_id)
         schema = program.graph.settings.vars_schema
         self.sched.init_vars({k: p.get("default") for k, p in sorted(schema.get("properties", {}).items())})
-        self.sched.start()
+        if target is not None:
+            self.sched.start_target(target)
+        else:
+            self.sched.start()
 
     async def _outputs_by(self, end: RunEnd) -> tuple[RunEnd, dict[str, Any] | None]:
         """The workflow's outputs, within the run's deadline. Past it, their evaluation is cancelled and the run ends
```

- [ ] **Step 4: Record the new scenario**

Run: `uv run --frozen python -m tests.engine.replay.record`. Expected: "dewpoint-0.1.0+abi8: recorded single_step".

- [ ] **Step 5: Run them again**

Run: the command of Step 2. Expected: PASS, 662 passed and 1 skipped. The CEL and runtime suites
show a normal run's views bind as before.

- [ ] **Step 6: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add backend/src/dewpoint/engine/runtime/seeds.py backend/src/dewpoint/engine/runtime/activities.py \
  backend/src/dewpoint/engine/runtime/scheduler.py backend/src/dewpoint/engine/runtime/execution.py \
  backend/src/dewpoint/engine/runtime/workflow.py backend/src/dewpoint/engine/cel/bind.py \
  backend/src/dewpoint/engine/runtime/resolve.py backend/tests/apps/worker/test_run_graph_seeded.py \
  backend/tests/engine/runtime/test_seeds.py backend/tests/engine/replay/scenarios.py \
  backend/tests/engine/replay/dewpoint-0.1.0+abi8
git commit -m "feat(engine): a single step runs alone from its seeds (S2, 4d-1 §5.3–§5.4)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: A run's end rows are spread over projections

**Spec:** §3.3 (D-a6), §9; engine 2b spec §5.3.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/execution.py` (`ENDS_PER_PROJECTION`, `_ends_pending`, `_rows_ready`,
  the drive loop, `_project_end`)
- Modify: `backend/tests/apps/worker/test_run_graph_ends.py`
- Create: `backend/tests/engine/runtime/test_end_rows.py`

**Interfaces:**
- Consumes: Task 5's `_queue_end`, `_queue`, `_take_rows`, `_project`.
- Produces: `ENDS_PER_PROJECTION = 500`; `Execution._ends_pending: deque[tuple[Instance, str, str]]`;
  `Execution._end_keys: set[tuple[str, str, int]]`; `Execution._rows_ready() -> bool`; `_queue` and `_queue_end`
  return the row's key.

Without it, the activation that ends a run makes a row for every open instance at once. A run that ends with
thousands of them spends one workflow task's CPU on it, which the engine bounds (engine 2b spec §5.3). The ends wait
in a queue instead. They become rows as each projection is sent, until 500 wait, those a byte-cut projection left
counted, so no projection carries more; the run's end is projected last (ruling 7). The unit test counts the end rows
per projection on the execution's own queue, with rows near their preview bound ahead of them.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_ends.py b/backend/tests/apps/worker/test_run_graph_ends.py
--- a/backend/tests/apps/worker/test_run_graph_ends.py
+++ b/backend/tests/apps/worker/test_run_graph_ends.py
@@ -249,3 +249,40 @@ async def test_a_simulated_delay_that_resolves_to_a_bad_value_fails_as_live(env:
     (live, simulated) = results
     assert live.status == simulated.status == "failed"
     assert live.error and simulated.error and live.error["code"] == simulated.error["code"]
+
+
+@dataclasses.dataclass
+class Batches(MemoryStore):
+    """Each projection's count of `not_started` rows: how a run's ends are spread."""
+
+    unstarted: list[int] = dataclasses.field(default_factory=list)
+
+    async def project(self, data: ProjectInput) -> None:
+        self.unstarted.append(sum(1 for r in data.steps if r.status == "not_started"))
+        await super().project(data)
+
+
+async def test_a_run_that_ends_with_many_open_instances_rows_them_over_several_projections(
+    env: WorkflowEnvironment,
+) -> None:
+    """A workflow task's CPU (engine 2b spec §5.3): ends are made into rows at most ENDS_PER_PROJECTION at a time, one
+    projection each, never all in the activation that ended the run. `f` fails at once; of the 1,197 steps the loop
+    opened beside it (3 iterations of 399: a graph holds 500 steps), the in-flight cap starts 100 or fewer, and the
+    rest never start."""
+    store = Batches()
+    g = graph().node("f", FAIL_N, {"failures": 10})
+    g.nodes[0]["options"]["max_attempts"] = 1
+    g.node("l", LOOP, {"items": [0, 1, 2], "concurrency": 3})
+    for n in range(399):  # slow: a quick body beside the failure meets a known hang on main (its own task)
+        g.node(f"e{n}", SLOW, {"seconds": 30}).edge("l", f"e{n}", "body")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {})
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+    assert result.status == "failed"
+    rows = store.steps(run_id_of(handle))
+    assert len({(r.node_key, r.iteration_key) for r in rows}) == 2 + 3 * 399  # every instance has its row
+    unstarted = [n for n in store.unstarted if n]
+    assert sum(unstarted) >= 1_000 and max(unstarted) <= 500 and len(unstarted) >= 3
+    from dewpoint.engine.runtime.execution import ENDS_PER_PROJECTION
+
+    assert ENDS_PER_PROJECTION == 500  # below what a projection's bytes allow (about 700 such rows): it's what cuts
diff --git a/backend/tests/engine/runtime/test_end_rows.py b/backend/tests/engine/runtime/test_end_rows.py
new file mode 100644
--- /dev/null
+++ b/backend/tests/engine/runtime/test_end_rows.py
@@ -0,0 +1,39 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A run's end rows, as projections send them (B4b; the simulation design §9): however a projection's byte cut
+divides what waits, none carries more than ENDS_PER_PROJECTION end rows, and each call makes at most that many. Counted
+in rows, on the execution's own queue, without a workflow."""
+
+import collections
+import uuid
+from types import SimpleNamespace
+
+from dewpoint.engine.runtime import scheduler as live_state
+from dewpoint.engine.runtime.activities import StepRow
+from dewpoint.engine.runtime.execution import ENDS_PER_PROJECTION, Execution
+from dewpoint.engine.runtime.scheduler import Instance
+
+NOW = "2026-10-13T00:00:00+00:00"
+
+
+def execution() -> Execution:
+    """An execution's row queue alone: `_queue_end` needs only the step an instance is of."""
+    ex = Execution.__new__(Execution)
+    ex.run_id = str(uuid.UUID(int=1))
+    ex.sched = SimpleNamespace(step=lambda inst: SimpleNamespace(id=inst.step, key="s", control=False))
+    ex._rows, ex._ends_pending = {}, collections.deque()
+    ex._started, ex._cel_modes, ex._finished, ex._attempted, ex._end_keys = {}, {}, set(), set(), set()
+    return ex
+
+
+def test_a_byte_cut_projection_never_sends_more_than_its_end_rows_limit() -> None:
+    ex = execution()
+    for n in range(100):  # rows waiting already, each with a preview near its 8 KiB bound
+        ex._queue(
+            StepRow(ex.run_id, str(uuid.UUID(int=10_000 + n)), "big", "", 1, "succeeded", output_preview="x" * 4000)
+        )
+    ex._ends_pending.extend((Instance((("l", n),), uuid.UUID(int=2)), live_state.UNSTARTED, NOW) for n in range(2_000))
+    per_projection: list[int] = []
+    while ex._rows_ready():
+        per_projection.append(sum(1 for r in ex._take_rows() if r.status == "not_started"))
+    assert sum(per_projection) == 2_000 and not ex._rows and not ex._ends_pending
+    assert max(per_projection) <= ENDS_PER_PROJECTION == 500
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/worker/test_run_graph_ends.py
tests/engine/runtime/test_end_rows.py tests/engine/replay`

Expected: FAIL, 1 failed, 65 passed and 1 error. One projection carried more than 500 ends (the check's run: `assert
(1098 >= 1000 and 593 <= 500)`): only the projection's byte cut divided them. The unit test can't import
`ENDS_PER_PROJECTION`.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -16,6 +16,7 @@ import dataclasses
 import hashlib
 import json
 import uuid
+from collections import deque
 from collections.abc import Generator, Mapping, Sequence
 from dataclasses import asdict, dataclass, replace
 from datetime import UTC, datetime, timedelta
@@ -130,6 +131,9 @@ with workflow.unsafe.imports_passed_through():
 
 IN_FLIGHT_CAP = 100  # activities and child workflows outstanding per execution (spec §6)
 PROJECT_BYTES = 256 * 1024  # a projection's rows at most, as JSON: far below Temporal's 2 MiB payload limit
+# Ends without settling (B4b) made into rows per projection, at most: a run that ends with thousands of open instances
+# rows them over several workflow tasks, each projection's, never in one (a workflow task's CPU, engine 2b spec §5.3)
+ENDS_PER_PROJECTION = 500
 CEL_BATCH = 1_000  # binding sets per cel.evaluate request
 CEL_REQUEST_BYTES = 1_835_008  # a cel.evaluate request's JSON bytes, a margin under Temporal's 2 MiB limit (#15)
 REQUEST_TOO_LARGE = "The values this expression reads are too large to send to the CEL evaluator (over 1.75 MiB)."
@@ -299,6 +303,8 @@ class Execution:
         self._finished: set[Instance] = set()
         self._effects: dict[Instance, dict[str, Any]] = {}
         self._not_waited: dict[Instance, Any] = {}  # a simulated timer's resolved config, for its row (§4.2)
+        self._ends_pending: deque[tuple[Instance, str, str]] = deque()  # (instance, how, when): rowed as projected
+        self._end_keys: set[tuple[str, str, int]] = set()  # the rows made of them that wait for a projection
         self.seeds: Seeds | None = None  # a single-step run's (S2): its scope, in place of the scheduler's
         self._projects = 0
         self._timers: dict[Instance, datetime] = {}  # a timer step asleep -> its wake time
@@ -427,7 +433,7 @@ class Execution:
                 for unit in startable[: max(0, IN_FLIGHT_CAP - self._in_flight(tasks))]:
                     waiting.remove(unit)
                     tasks[unit] = asyncio.create_task(self._unit(unit))
-                if self._rows and not any(key[0] == "project" for key in tasks):  # one at a time: rows wait for it
+                if not any(key[0] == "project" for key in tasks) and self._rows_ready():  # one at a time
                     self._projects += 1
                     tasks[("project", self._projects)] = asyncio.create_task(self._project(self._take_rows()))
                 if not tasks and self._ask is None and self.sched.queued_left():
@@ -702,7 +708,7 @@ class Execution:
 
     # --- the projection -------------------------------------------------------------------------------------------
 
-    def _queue(self, row: StepRow) -> None:
+    def _queue(self, row: StepRow) -> tuple[str, str, int]:
         """Queue a row for the next projection, as storage will write it: `_take_rows` sizes the rows it sends, and a
         character strict UTF-8 can't encode would fail that in workflow code, on every retry. A later row of the same
         attempt replaces it."""
@@ -714,7 +720,9 @@ class Execution:
             error_code=sanitize(row.error_code),
             error_message=sanitize(row.error_message),
         )
-        self._rows[(row.step_id, row.iteration_key, row.attempt)] = row
+        key = (row.step_id, row.iteration_key, row.attempt)
+        self._rows[key] = row
+        return key
 
     def _take_rows(self) -> list[StepRow]:
         """The next projection's rows, oldest first, within PROJECT_BYTES; one row at least. A backlog (after a
@@ -726,6 +734,7 @@ class Execution:
             if taken and size + row_size > PROJECT_BYTES:
                 break
             taken.append(self._rows.pop(key))
+            self._end_keys.discard(key)
             size += row_size
         return taken
 
@@ -760,8 +769,16 @@ class Execution:
                     effect_preview=self._effects.pop(inst, None),
                 )
             )
-        for inst, kind in self.sched.take_ends():
-            self._queue_end(inst, kind, now)
+        self._ends_pending.extend((inst, kind, now) for inst, kind in self.sched.take_ends())
+
+    def _rows_ready(self) -> bool:
+        """Ends made into rows, up to ENDS_PER_PROJECTION waiting at once (what a byte-cut projection left counts),
+        so no projection carries more; then whether any row waits for one."""
+        for _ in range(min(ENDS_PER_PROJECTION - len(self._end_keys), len(self._ends_pending))):
+            key = self._queue_end(*self._ends_pending.popleft())
+            if key is not None:
+                self._end_keys.add(key)
+        return bool(self._rows)
 
     def _row(self, inst: Instance, status: str, **fields: Any) -> StepRow:
         step = self.sched.step(inst)
@@ -775,21 +792,20 @@ class Execution:
             **fields,
         )
 
-    def _queue_end(self, inst: Instance, kind: str, now: str) -> None:
+    def _queue_end(self, inst: Instance, kind: str, now: str) -> tuple[str, str, int] | None:
         """An instance that ended without settling (B4b; the simulation design §3.3): `skipped` and `not_started`
         record attempt 1 and no start. A stopped one was handed out: `cancelled` once it began (a control step, or a
         plugin step still resolving its values), `not_started` if it never did. A plugin step that reached an attempt
-        rows its own end, and a unit that finished has its real outcome (D-a3)."""
+        rows its own end, and a unit that finished has its real outcome (D-a3). The row's key, if it made one."""
         step = self.sched.step(inst)
         if kind == live_state.STOPPED:
             if inst in self._finished or (not step.control and inst in self._attempted):
-                return
+                return None
             if inst in self._started:
-                self._queue(self._row(inst, "cancelled", started_at=self._started[inst], ended_at=now,
-                                      cel_mode=self._cel_modes.get(inst)))  # fmt: skip
-                return
+                return self._queue(self._row(inst, "cancelled", started_at=self._started[inst], ended_at=now,
+                                             cel_mode=self._cel_modes.get(inst)))  # fmt: skip
         status = "skipped" if kind == live_state.SKIPPED else "not_started"
-        self._queue(self._row(inst, status, ended_at=now))
+        return self._queue(self._row(inst, status, ended_at=now))
 
     @staticmethod
     def _effect_of(effect: "_Effect") -> dict[str, Any] | None:
@@ -858,8 +874,9 @@ class Execution:
         self._queue_settled()
         cancelled = False
         while True:
+            self._rows_ready()
             rows = self._take_rows()
-            last = not self._rows
+            last = not self._rows and not self._ends_pending
             if rows or (last and summary is not None):
                 cancelled = await self._shielded(rows, summary if last else None) or cancelled
             if last:
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 67 passed. The abi8 histories replay as recorded: their runs end with
fewer than 500 open instances.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/engine/runtime/execution.py backend/tests/apps/worker/test_run_graph_ends.py \
  backend/tests/engine/runtime/test_end_rows.py
git commit -m "fix(engine): a run's end rows spread over projections, 500 at most each (B4b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Every check, the ledger, the final checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`

- [ ] **Step 1: The whole backend suite, CodeQL**

Ask the owner before the backend suite (about 12 minutes with `-n auto`). Then:
- `uv run --frozen pytest -q -n auto` from `backend/`, with the CEL gate tests too, as CI runs them;
- ruff (format and check), mypy, the import linter;
- local CodeQL on the branch's head (`scratchpad/codeql/scan.sh <sha>`): no new alert.

Expected: every one passes. A failure is read and fixed test-first, or reported as it is: never a claim that every
check passes when one didn't. Nothing in the frontend changed, so its checks aren't run.

- [ ] **Step 2: The ledger**

Append `### 4d-1a, milestone 3 and the final checkpoint (date)`: the tasks' commits, each check's result as run (the
suite's counts), every mid-slice ruling, anything deferred. Commit (`docs(editor-4): 4d-1a final checkpoint`).

- [ ] **Step 3: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch:
- against this plan (its Review Focus first) and the spec's §3–§5 and §8;
- with the ledger's rulings in view.

Critical and important findings are fixed test-first, once; minor ones are listed. Then **stop**. The summary to the
owner names:
- what's built, and the checks as run;
- the rulings proposed and made, and whether rulings 2, 3, 13 and 16 changed the spec or are still open;
- the deploy order (0071 before the ABI-8 workers).

It asks for the owner's word on push and a PR; nothing is pushed before it. CI on the PR runs the backend (about 12
minutes), the frontend, CodeQL and the Compose e2e: say so before pushing.
