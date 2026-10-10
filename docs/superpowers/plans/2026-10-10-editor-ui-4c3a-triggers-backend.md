# Editor UI 4c-3a: Triggers, the Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 5, 2026-10-10.** Nothing is built before the owner approves this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat. Reviews pasted in chat held revision 1 for two P2 findings in Task 7 and two
minor ones, revision 2 for one P2 in Task 7, revision 3 for two P2 in Task 7, and revision 4 for one P2 in Task 7; the
"Changes from revision N" sections say how each was answered.

The plan's code was checked before review on a scratch copy of main at aed887f8, never on a branch. Its blocks were
applied as written, task by task, each task's tests run red and then green, and the plan corrected where they failed:
- the backend tests of the directories the tasks touch (`tests/apps/api`, `tests/core/ingress`, the schedule, summary,
  sync and ingress tests, the migration chain and model schema): 781 passed; erasure, retention and keys: 99 passed;
  after revision 5's changes, `tests/apps/api` and the shape check's own tests again: 487 passed;
- the frontend's unit suite after the regenerated types: 828 passed; `check:api` and `typecheck` clean;
- ruff (check and format), mypy on `src` (285 files) and the import contracts (11 kept): clean.

The whole backend suite wasn't run; Task 10 runs it, with the owner's OK. The executor still runs every step: the
check is evidence, not a substitute.

## Changes from revision 4

It answers the review of revision 4, pasted in chat on 2026-10-10. Each new test fails on revision 4's code (its module
put back in place for the run) and passes on revision 5's.

1. **P2, a nested `$schema` switched back to the unbudgeted validator.** When jsonschema descends into a subschema,
   `evolve()` picks the validator registered for that subschema's `$schema`. The check's extended class, with its
   steps and its lazy `anyOf`, was left behind. On revision 4, a union under `$schema` naming 2020-12 built 60,001
   errors over the review's input after 2 counted steps. With a 4-step budget, a fitting 20,000-item list beneath one
   completed without a schedule counted unchecked. Now:
   - **No rewriting but one key.** The draft's document is kept as written, so references and definitions resolve as
     they do for the draft. Only `$schema` naming 2020-12, the check's own dialect, is removed, wherever a schema
     stands (`schema_refs`' schema positions). Nothing then names another validator: every subschema, reached by
     descent or by reference, is checked by the check's own class. jsonschema's registered validators are left as
     they are.
   - **What isn't structure is evaluated as nothing.** The extended validator evaluates only structural keywords;
     every other keyword holds (`oneOf` as the lazy `anyOf`). Before, they were deleted from the document, which
     could leave a reference's target or `patternProperties`' effect on `additionalProperties` behind; now they
     stay, unevaluated.
   - **Another dialect isn't checked.** A schema naming one is read by that dialect's rules, which the check doesn't
     keep. The check spends nothing, gives no reason, and names `$schema` in `schedule.partly_checked`.

   On the review's union: 4 errors in 10 steps, whether `$schema` sits on the union or in each branch. Tests:
   - Task 7's unit tests:
     - `test_a_dialect_declared_inside_never_leaves_the_checks_validator`, on the union and in each branch (failing
       branches);
     - `test_a_dialect_declared_inside_still_spends_the_budget` (a fitting list beneath a nested `$schema`, through a
       reference);
     - `test_another_dialect_isnt_checked_and_says_so`;
     - `test_a_key_its_pattern_allows_is_no_extra_field`;
     - `test_a_reference_resolves_wherever_its_schema_stands` (a guard: it passes on revision 4 too, since drafts'
       references are `#/$defs/<name>` only);
   - its API test: `test_a_dialect_declared_inside_is_budgeted_through_validate` (fitting branches, counted
     unchecked when the steps run out).

## Changes from revision 3

It answers the review of revision 3, pasted in chat on 2026-10-10. Each new test fails on revision 3's code (its module
put back in place for the run) and passes on revision 4's.

1. **P2, the error limit didn't bound the work inside `anyOf`.** JSON Schema's own `anyOf` builds every error of a
   failing branch (`list(…)`) before it yields its one error. Over the review's 400 KB input, three branches built
   60,001 errors before the check saw one (counted on revision 3's code), and the worker thread bounded neither CPU
   nor memory. Now the budget is enforced inside the evaluation:
   - **Every keyword spends a step.** The check runs JSON Schema's own validator, extended (`validators.extend`) so
     that every keyword, at any depth, spends one of the check's 50,000 steps (`MAX_STEPS`, for all its inputs
     together) before it's evaluated.
   - **An explicit incomplete result.** When the steps run out, the check stops (`Exhausted`): the input it was in
     and the rest are counted in `schedule.unchecked`, whose text names the step budget too.
   - **A lazy `anyOf`.** The check's `anyOf` tries each branch only up to its first error, and keeps none (the check
     never names them). The review's union now builds 4 errors, in 10 steps.

   Tests:
   - Task 7's unit tests: `test_a_union_is_tried_branch_by_branch_up_to_a_first_error` and
     `test_every_step_of_the_check_spends_from_one_budget` (a check that runs out, and `checked_all` counting the
     rest);
   - its API test: `test_a_check_that_runs_out_of_steps_counts_the_rest_unchecked`.
2. **P2, the 2 MiB budget was applied after every input was fetched.** One statement (`read_schedules`) now picks
   the oldest schedules whose sealed inputs fit 2 MiB together, 100 at most, by their stored length. It uses window
   functions over `octet_length`, which reads no payload. It joins back for those inputs only, and returns the others
   as ids with the live total, in the same snapshot. Test: `test_past_the_byte_budget_no_stored_input_is_fetched`
   (the second schedule's row comes back without its input).

## Changes from revision 2

It answers the review of revision 2, pasted in chat on 2026-10-10. Each new test fails on revision 2's code (its three
files put back in place for the run) and passes on revision 3's.

1. **P2, one stored input's check had no bound on its work or its answer.** It drained every error, built every
   indexed reason and sorted them, in the request, on the event loop. A 400 KB input whose 20,000 items broke a new
   item type gave 20,000 reasons, a 909 KB answer for one schedule. The check is now bounded in work units, never
   time:
   - **One stored input:** its errors are read lazily (jsonschema yields them one by one), and the check stops at
     100 errors read (`MAX_ERRORS`) or 5 distinct reasons kept (`MAX_REASONS`). Slicing a finished list would not
     bound the work. Each reason is 300 characters at most (`MAX_REASON_CHARS`): a name the draft gives may be long.
   - **One check:** on top of the 100 schedules, at most 2 MiB of their sealed input is read (`MAX_INPUT_BYTES`), the
     oldest first. Past it, the rest are counted in `schedule.unchecked`, whose text now names both bounds.
   - **Said truthfully:** a schedule whose reasons stopped at a bound says `more: true` in `schedule_breaks`
     (`ScheduleBreakOut.more`).
   - **Off the event loop:** decoding the inputs, reducing the draft's input and checking run in a worker thread
     (`checked_all`, through `asyncio.to_thread`). Only reading the rows and unsealing them stay on the loop.

   Ruling 7 now says so. Tests:
   - Task 7's unit tests: `test_a_stored_input_is_read_within_its_budgets` (the review's 20,000 items),
     `test_the_errors_read_are_bounded_whatever_the_validator_yields` (an endless validator: only the budget stops
     it), `test_a_reason_is_bounded_in_length`;
   - its API tests: `test_one_large_input_gives_a_bounded_answer` (the review's witness, through validate: 5 reasons,
     `more`, an answer under 20 KB), `test_the_stored_input_one_check_reads_is_bounded_in_bytes`,
     `test_the_check_runs_off_the_event_loop`.

## Changes from revision 1

It answers the review of revision 1, pasted in chat on 2026-10-10. Each new test fails on revision 1's code (its
module put back in place for the run) and passes on revision 2's.

1. **P2, the shape check read only the root.** A required field under an object, a type behind a `$ref`, a
   requirement in an `allOf`: each breaks every firing, and validate said nothing. The check now reduces the draft's
   input to its shape and runs JSON Schema's own validator on it:
   - What it keeps is structure: `type`, `properties`, `required`, `additionalProperties`, `items`, `prefixItems`,
     references and their definitions, `allOf`, `anyOf`, `dependentRequired`, `dependentSchemas`.
   - Every keyword that tests a value's content is dropped, as before (never full validation).
   - `oneOf` is read as `anyOf`; `not`, `if`/`then`/`else`, `propertyNames`, `patternProperties`, `unevaluated*`
     and `contains` are dropped.
   - Only keywords are dropped, so the shape accepts every value the draft does: what it refuses, the draft refuses
     (no false warning).
   - What it couldn't keep is named in a new warning, `schedule.partly_checked`, whenever a live schedule was read.

   Ruling 7 now says so. Tests:
   - Task 7's unit tests: `nested-required`, `reference`, `all-of`, `items`, `any-of`, `nested-no-longer-allowed`,
     `dependent-required`, and `test_structure_the_shape_cant_keep_is_named_and_never_refuses`;
   - its API tests: `test_validate_reads_nested_fields_references_and_all_of` and
     `test_structure_the_check_cant_read_is_said`.
2. **P2, `2.0` was refused as an integer.** JSON Schema's type checker (the validator's own) now decides types, so
   an integral number is a whole number, and a boolean still isn't. Tests: `test_an_integral_number_is_a_whole_number`
   (unit) and `test_an_integral_number_fits_a_whole_number` (API: an unchanged input with a stored `2.0`).
3. **P3, the rows and their count were read apart**, so a deletion between them could make the unchecked number
   negative. One statement reads the oldest 100 and their total (`count(*) OVER ()`), in one snapshot. Test:
   `test_the_schedules_and_their_number_come_from_one_statement`.
4. **P3, `$PY` held a multiword command**, which zsh doesn't split. Every command is now written out whole ("How to
   run things").

**Goal:** the backend 4c-3b's trigger setup needs: an endpoint that records the trigger it's for, a workflow's webhook
bindings (B13), the list's trigger counts and its schedule-sync attention, a schedule answer that says what its sync
proves, a warning when a draft would break live schedules, and named answers for every trigger route the editor calls.

**Architecture:** one hand-written migration (0054) adds `webhook_endpoints.trigger_key`, set from `/trigger-types`
when an endpoint is made and never updated. Everything else is the API layer: `apps/webhooks.py`,
`apps/schedules.py`, `apps/workflow_summary.py`, a new `apps/schedule_checks.py`, the routes, and models in
`apps/api/responses.py`; then the OpenAPI document and the web client's types are regenerated. The engine is
untouched.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, PostgreSQL 16 (testcontainers),
pytest; openapi-typescript for the client's types.

**Spec:** `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md` (§2 4c's trigger setup, §5's B13 row), the
ledger `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (rulings 68, 69, 71, 74, 96), the owner's 4c-3
rulings in chat on 2026-10-10 (Task 1 writes them into the ledger), and the D8 mockups the owner signed off: the
Design canvas "4c-3 Trigger Mockups", version 21 (https://claude.ai/artifact/TvL7JjYvqSCMgtGJSmmr3a, private).

## Global Constraints

- **ENGINE_ABI stays 6.** No file under `backend/src/dewpoint/engine/` changes; the golden replays under
  `tests/engine/replay/` pass unchanged.
- **One migration, 0054** (the owner's slot, 2026-10-10), `down_revision = "0045"` (main's head). Written by hand:
  never Alembic autogenerate. A nullable column with no default (a catalog change, no rewrite). The API's role gets
  no UPDATE grant on it. 2b-4b's unmerged 0050–0053 aren't on main: whichever merges second rechains its first
  migration onto the head it meets (the ledger's slot rules). Deployed migrations are never edited.
- **Every route the editor calls answers a named model** in `apps/api/responses.py`, named uniquely. The OpenAPI
  document is regenerated and committed with the client's types; `check:api` and CI's "API schema is current" diff
  stay clean.
- **Permissions, unchanged:** endpoints and bindings are written with `trigger.manage` and read with
  `workflow.view`; validate needs `workflow.edit`, publish `workflow.publish`, the start form `run.start`. Every
  query is the tenant's (row-level security, and an explicit tenant filter in the list's statements).
- **A schedule's stored input is never shown, logged or quoted.** The draft check reads its shape only (Task 7):
  whether a field the draft requires is there, whatever its depth; whether a value has the JSON type the draft
  declares; whether a field the draft no longer allows is there. Never a value's content, never a stored field's
  name. Logs name an exception's type only.
- **No real Mist or SaaS call, ever.** Tests use the demo trigger types, the testkit and flow plugins, and fakes.
- **Verify, don't remember.** Every library API is checked in the installed package before it's relied on
  (SQLAlchemy's `and_`, Pydantic's `Field(alias=…)` in a response model, FastAPI's `response_model_exclude_unset`).
- **The frontend gets no new package and no screen**: only `openapi.json`, `schema.d.ts` and three test fixtures
  change.
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker (the owner, 2026-10-08). Nothing is
  pushed and no PR is opened without the owner's OK in chat. Ask before any local run expected over 10 minutes.

## Review Focus

These are the inputs and conditions most likely to bite a person using this. Each is pinned by the test named, in
the task that owns the code.

- **A plugin's later version stops declaring a trigger.** Endpoints made for it keep the key they were made for (the
  editor says the sender is unknown); no new endpoint can name it. Task 3:
  `test_an_endpoint_keeps_its_trigger_when_a_plugin_stops_declaring_it`.
- **A trigger whose endpoint is signed (`hmac`).** No synced plugin declares one today. The endpoint takes the
  default signature and timestamp headers and an HMAC secret, shown once. Task 3:
  `test_an_endpoint_for_a_signed_trigger_takes_the_default_headers`.
- **The list's CSV flag and an unpublished draft.** A draft that would take a CSV file doesn't change the list's
  Trigger column until it's published. Task 6: `test_the_list_says_what_starts_each_workflow`.
- **A draft whose input schema has an error.** It can't be checked against: validate says its error and nothing about
  the schedules, never a failure of its own. Task 7: `test_a_draft_whose_input_schema_is_wrong_isnt_checked`.
- **Publishing a draft that takes a CSV file over live schedules.** It publishes, and the warning points at the CSV
  declaration. Task 7: `test_publishing_a_csv_draft_warns_at_its_declaration`.
- **A draft's input with structure a shape can't keep** (`not`, `if`, `oneOf`'s one-only rule). The check widens,
  never warns falsely, and says it read the schedules in part. Task 7: `test_structure_the_check_cant_read_is_said`.
- **One very large stored input** (400 KB, under the request limit) that breaks at every item. The check's work and
  its answer stay bounded, and it says it stopped. Task 7: `test_one_large_input_gives_a_bounded_answer`.

## Rulings this plan proposes

These join the ledger as rulings 139 onward once the owner accepts the plan. Each says why, and what it costs if
it's wrong.

1. **An endpoint records the trigger it's for** (Tasks 2–3; migration 0054).
   - `POST …/webhook-endpoints` takes `trigger`: the key of a trigger type a synced plugin declares
     (`mist.webhook`), or null for another sender.
   - Named, the endpoint takes that trigger's endpoint settings: how it proves its sender (`auth`), where its events
     are (`events_pointer`), and no ids (`id_source: none`).
   - Refusals are `422 endpoint_invalid` with `fields`: a key no synced plugin declares is `["trigger"]`; a setting
     the request writes that the trigger decides otherwise is named (writing the same is no clash).
   - Stored as `webhook_endpoints.trigger_key`, never changed: PATCH refuses it, and the API's role has no grant to
     update it. Every endpoint answer says `trigger`; the create audit records it.
   - Endpoints made before 0054 have none: they read as another sender's.
   - Why: the editor offers Mist's topics and shapes only for a Mist endpoint, and an endpoint's settings decide how
     its deliveries are read, so they never change. Cost: an existing Mist endpoint shows as another sender's until
     it's remade.
2. **B13: a workflow's webhook bindings** (Task 4). `GET …/workflows/{workflow_id}/webhook-bindings`, read with
   `workflow.view`.
   - Each binding comes with what the Triggers panel shows of its endpoint: id, name, enabled, auth, path, trigger.
   - Ordered by the endpoint's name, then its id. One statement; `trigger_bindings_one`'s tenant prefix serves it, so
     no new index.
   - A workflow the caller's tenant doesn't have, unknown or another tenant's, is `404 not_found`.
   - Why: until now bindings are listed per endpoint only. Cost: none known.
3. **The list says what starts each workflow** (Task 6). Each row (and a workflow's own answer) carries
   `triggers: {schedules, schedules_enabled, webhook_bindings, csv}`.
   - Schedules are the live ones: a deleted one's tombstone is left out.
   - Bindings are counted on or off.
   - `csv` is whether the active version declares a CSV file, never the draft; false when nothing is published.
   - One more batched statement: the list's reads are still fixed, whatever its number of workflows (7 at most).
   - Why: 1a's Trigger column (ruling 68). Cost: one statement per list read.
4. **A schedule that failed to sync needs attention** (Task 6). `needs_attention` gains `schedule_sync_failed`.
   - Raised when a live schedule of the workflow, on or off, has `sync_error` set; a tombstone's never raises it.
   - It clears when the sync next succeeds (the sync clears `sync_error` when it records a generation).
   - Why: ruling 74's "schedules' sync errors join with 4c". Cost: a disabled schedule's failed sync raises
     attention though its firings are refused at admission. The failure is real, and it's retried every minute.
5. **Named answers for the trigger routes** (Task 8). Every trigger route the editor will call answers a named model,
   and so does the start form:
   - schedules: create, list, read, update;
   - endpoints: create (its secret shown once), list, read, update, rotate;
   - bindings: create, an endpoint's list, update, a workflow's list (B13);
   - the start form, whose omitted keys stay omitted (`response_model_exclude_unset`).

   A schedule's uncounted span keeps its wire names `from` and `class` (aliases). `sync_error` is a string, its codes
   in a comment: a new code would otherwise fail every answer that holds it. Why: the client is generated from the
   schema (B1). Cost: none known.
6. **A schedule says what its sync proves** (Task 5). Its answer adds:
   - `sync_error_at`: an edit doesn't clear a failure, so the editor can tell an earlier one from the latest edit's;
   - `never_unpaused`: true only when no incarnation of it was sent an unpause, none was seen unpaused, and none is
     from before 2b-4a (whose unpauses nobody recorded). A schedule is created paused and only the sync unpauses it,
     recording that first, so with none recorded it has never fired, and the editor may say "not running yet".

   Why: the owner's ruling (2026-10-10), after the D8 review found "never synced" proves nothing. Cost: none known.
7. **A draft that would break live schedules is said so** (Task 7). Validate and publish check the workflow's live
   schedules' stored input against the draft's (or the new version's) input, server-side:
   - **Shape only.** JSON Schema's own validator (its own types: `2.0` is an integer), extended for the check,
     checks the stored input against the draft's input as written. It evaluates only structure: `type`,
     `properties`, `required`, `additionalProperties`, `items`, `prefixItems`, references, `allOf`, `anyOf`,
     `dependentRequired` and `dependentSchemas`, at any depth. So it finds a field the draft requires that isn't
     there, a value whose JSON type isn't the one the draft declares, a field the draft no longer allows, an extra
     item.
   - **Never a value's content.** Every keyword that tests one holds for every value (`const`, `enum`, `maximum`,
     `minimum`, `multipleOf`, `maxLength`, `minLength`, `pattern`, `format`, `minItems`, `maxItems`, `uniqueItems`,
     `minProperties`, `maxProperties`). Checking one against a stored value would let whoever can validate a draft
     learn a sensitive value a bit at a time. What the check can tell is presence, a value's JSON type, and a list's
     length against the items the draft declares.
   - **Structure a shape can't keep holds, and is said.** `oneOf` is evaluated as `anyOf` (its one-only rule
     dropped). `not`, `if`/`then`/`else`, `propertyNames`, `patternProperties`, `unevaluatedProperties`,
     `unevaluatedItems` and `contains` hold for every value: evaluating any of them without its value keywords could
     refuse what the draft accepts. So the check accepts every value the draft does: a stored input it refuses, the
     draft refuses too, and no warning is false. When the draft uses one of them and a live schedule was read, a
     `schedule.partly_checked` warning names them.
   - **The check never leaves its own validator.** The draft's document is kept as written, so references resolve as
     they do for the draft, but for `$schema`. jsonschema validates a schema it descends into with the validator its
     `$schema` names, which has no budget. So `$schema` naming 2020-12, the check's own dialect, is removed wherever a
     schema stands. Another dialect is read by its own rules: a draft naming one isn't checked, and the warning names
     `$schema`.
   - **The reasons are the draft's own words.** A place is named as far as the draft declares it (a key the data
     supplied shows as `*`), a field by the draft's name; never a value, never a stored field's name. A draft that
     takes a CSV file fits no schedule: its rows come from an upload only.
   - **A warning, never a refusal.** `schedule.input_refused` at `/settings/input_schema`, or `/settings/csv` for a
     CSV file. Validate's answer lists the schedules (`schedule_breaks`: id, reasons, and `more` when a bound cut them
     short; the oldest first).
   - **Bounded in work units, never time.**
     - A check fetches the oldest live schedules whose sealed inputs fit 2 MiB together, 100 at most. They are picked
       by their stored length in the statement that also counts them, so no other input is fetched.
     - Every keyword it evaluates, at any depth, spends one of its 50,000 steps, for all its inputs together. Its
       `anyOf` tries a branch only up to its first error and keeps none.
     - From one stored input it reads at most 100 errors, lazily, and keeps at most 5 distinct reasons, each of 300
       characters at most.
     - The rest are said: schedules past a bound, the one the steps ran out in, and any whose stored input can't be
       read (the tenant's key unreadable), in a `schedule.unchecked` warning; reasons past a bound as `more`.
     - Decoding and checking run in a worker thread, off the event loop.
   - **Skipped** when the draft's input schema or CSV declaration has an error.
   - Webhook bindings aren't checked here: the editor warns at the binding (the owner's ruling).

   Why: nobody can see a schedule's stored input, and a draft that no longer fits makes it fail at every firing.
   Costs:
   - a stored input that breaks only a value rule (a new `maximum`, a narrower `enum`) isn't reported: it fails at
     its first firing, as today, and the run says why;
   - one that breaks only the structure listed above as dropped is reported as checked in part, not as broken;
   - a schedule past the bounds isn't checked: it's counted, so the editor can say so.
8. **Migration slot 0054** (Task 2), the owner's (2026-10-10), chained after main's head, 0045. 0050–0053 are 2b-4b's.

## File Structure

New:
- `backend/migrations/versions/0054_endpoint_trigger.py`: `webhook_endpoints.trigger_key`.
- `backend/src/dewpoint/apps/schedule_checks.py`: whether a draft would break the live schedules, by shape.
- `backend/tests/apps/test_schedule_checks.py`: the shape check itself.
- `backend/tests/apps/api/test_schedule_checks_api.py`: validate's and publish's warnings.

Changed:
- `backend/src/dewpoint/core/models/ingress.py`: `WebhookEndpoint.trigger_key`.
- `backend/src/dewpoint/apps/webhooks.py`: an endpoint for a trigger (`_for_trigger`), `endpoint_summary`, the
  answer's `trigger`.
- `backend/src/dewpoint/apps/api/routes/webhooks.py`: `EndpointIn.trigger`, B13's route, named answers.
- `backend/src/dewpoint/apps/schedules.py`: `Accounting.never_unpaused`; the answer's `sync_error_at` and
  `never_unpaused`.
- `backend/src/dewpoint/apps/workflow_summary.py`: `TRIGGERS`, `TriggerStats`, `trigger_stats`; `attention`'s
  `schedule_sync_failed`.
- `backend/src/dewpoint/apps/api/routes/workflows.py`: the rows' `triggers`; validate's and publish's schedule check.
- `backend/src/dewpoint/apps/api/routes/schedules.py`, `routes/run_requests.py`: named answers.
- `backend/src/dewpoint/apps/api/responses.py`: the new models; `WorkflowOut.triggers`, its attention literal;
  `ValidationOut.schedule_breaks`.
- `backend/tests/core/test_migration_chain.py`, `tests/core/ingress/test_ingress_schema.py`,
  `tests/apps/api/test_webhooks_api.py`, `tests/apps/api/test_schedules_api.py`,
  `tests/apps/api/test_workflow_summary.py`, `tests/apps/api/test_openapi.py`: the tasks' tests.
- `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`: regenerated.
- `frontend/src/routes/editor/check.test.ts`, `DeclassifyPanel.test.tsx`, `ProblemsPanel.test.tsx`: their typed
  validation answers gain `schedule_breaks: []`.
- `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`: the owner's 4c-3 rulings, slot 0054, this plan's
  status, its mid-slice rulings.
- `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md`: §5's B13 row says where it was built.

## Milestones

1. **Endpoints and bindings** (Tasks 1–4): the ledger, migration 0054, an endpoint for a trigger, B13.
2. **Schedules and the list** (Tasks 5–7): what a schedule's sync proves, the list's triggers and attention, the draft
   check. **Pause:** the owner's review. Task 7 decides what validate may reveal of sealed input.
3. **The client's contract** (Tasks 8–10): the named answers, the regenerated client types, every check, the final
   checkpoint. **Pause:** a fresh reviewer, the summary; then stop.

## How to run things

Every command runs from the plan's worktree (see "Executing this plan"). `$WT` is that worktree's root. Each command
is written out whole: none is kept in a shell variable, which zsh wouldn't split into words (the review of revision 1).

- Python, from `$WT/backend`, uses the worktree's own environment, made from the lock: `uv sync --frozen` installs
  exactly `uv.lock` into `$WT/backend/.venv`. It installs packages, so the owner's OK is asked at the start. If it
  can't be made, the work stops for the owner's word: there is no fallback to another checkout's environment (the
  owner's review of the 4c-2a plan). Then:
  ```bash
  uv run --frozen python -c 'import dewpoint; print(dewpoint.__file__)'   # must print $WT/backend/src/...
  ```
- The database tests start PostgreSQL in Docker (testcontainers) and migrate it to head. Run them from
  `$WT/backend`, with Docker reachable: `uv run --frozen pytest -q -n auto tests/apps/api/test_webhooks_api.py`.
- One test: `uv run --frozen pytest -q tests/apps/api/test_webhooks_api.py::test_name`.
- Lint and types: `uv run --frozen ruff format src tests && uv run --frozen ruff check src tests`;
  `uv run --frozen mypy src`; `uv run --frozen lint-imports`.
- The whole backend suite (`-n auto`) takes about the CI job's 12 minutes, so the owner is asked before it runs. It
  runs at the end only; each task runs its own tests.
- The OpenAPI document, from `$WT/backend`:
  ```bash
  uv run --frozen dewpoint api openapi > ../frontend/src/api/openapi.json
  ```
  then, from `$WT/frontend` (after `npx --offline pnpm@12.6.0 install --frozen-lockfile --offline`, the locked
  packages only): `npx --offline pnpm@12.6.0 gen:api`, then `check:api`, `typecheck`, `lint`, `test`.
- Local CodeQL, at the end: `scratchpad/codeql/scan.sh <sha>` (about 40 s).

## Executing this plan

- **Inline**, by one implementing agent in one session, with the owner's reviews at the milestone pauses: after
  Milestone 2, and a fresh independent review at the end. Test-first, as each task's steps say. The owner chooses.
- **The branch** is settled with the owner at the start. The default proposed: `feat/editor-4c3a` from
  `origin/main`, in its own worktree, with this plan's docs branch merged into it first. A later main is merged in,
  never rebased.
- **Where the code base differs from a step** (a name, a line), the executor adapts the step test-first and records
  the difference as a mid-slice ruling in the ledger (M78 onward).
- **The rulings above** join the ledger only when the owner accepts the plan; until then the ledger says they're
  proposed.

---

# Milestone 1 — endpoints and bindings

### Task 1: The ledger: the owner's 4c-3 rulings, slot 0054, and this plan proposed

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (the "Migration slots" table; append at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger sections later tasks append to (`### 4c-3a, milestone N`).

- [ ] **Step 1: The slot**

In the "Migration slots" table, after the row for 0049, add:

```markdown
| 0054 | 4c-3a: `webhook_endpoints.trigger_key`, an endpoint's sender (the owner, 2026-10-10; 0050–0053 are 2b-4b's) |
```

- [ ] **Step 2: Append the owner's rulings and the plan's status**

Append exactly:

```markdown
### Owner, 4c-3 design and mockups (2026-10-10, in chat)

Asked with the research for 4c-3 (ruling 96's triggers), the owner chose:
- the start card opens a Triggers side panel (Input, Schedules, Webhooks); the card's "+" keeps adding the first step;
- the input as a field list (name, label, type, required, sensitive, description, default), "Use a Mist event…"
  copying a topic's shape from `/trigger-types` (read only, replaceable), an optional CSV file of typed columns, and
  an opt-in "Edit as JSON";
- schedules and webhooks are live and said so, outside undo; before the first publish "＋ Schedule" is disabled, with
  why;
- a schedule's timing, time zone, mode and on/off are editable; its input is replaced whole ("Replace the input…", on
  the published version's form), never shown back;
- an endpoint records its sender (a migration), set from `/trigger-types` when it's made, and fixed;
- 1b's "What starts it?" seeds the draft (a Mist topic's shape, or an empty CSV section), creates a Mist binding at
  once, offers a schedule after the first publish, and opens the new workflow on its Triggers panel;
- the backend, 4c-3a, all six: the endpoint's sender, B13, the list's trigger counts, `schedule_sync_failed`, named
  answers for the trigger routes, and validation that warns, server-side, when a draft would break live schedules;
- the UI, 4c-3b: one plan with milestones, after 4c-3a merges. The run form and CSV upload stay 4e's; the webhook
  events inbox is out of scope.

The open points, answered:
- a binding whose events don't fit the input is warned of at the binding, in the editor: a Mist binding compares its
  topic's shape with the published version's input and offers the topic's shape; another sender's says the input
  must fit its events;
- 1b with "Import from file": the file's input wins; the binding is still created, and Triggers warns;
- Settings → Webhook endpoints shows and copies the relative path now; "This deployment doesn't receive webhooks yet"
  shows only outside a development deployment; a public address setting comes later, with 2b-4b.

D8: pasted reviews held the canvas twice. Version 16: a failed sync isn't "not running", and boards were missing
(another sender's endpoint, CSV columns and JSON, the schedule variants, read-only and 320 px views). Version 19:
"never synced" isn't "not running" either, and the endpoint form's summary contradicted its pointer. Version 21
answered both, and a pasted review-side sign-off followed. The owner then:
- signed off D8 on the "4c-3 Trigger Mockups" canvas, version 21 (18 boards);
- assigned migration slot 0054 to the endpoint's sender;
- added a read-only "never unpaused" flag to the schedule answer, so a schedule nothing ever unpaused can say "not
  running yet".

### 4c-3a plan (2026-10-10)

`docs/superpowers/plans/2026-10-10-editor-ui-4c3a-triggers-backend.md`, revision 1. Its rulings (1–8) are proposed,
and join this ledger as 139 onward only when the owner accepts the plan.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): the owner's 4c-3 rulings, slot 0054, and the 4c-3a plan proposed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: An endpoint's trigger key (migration 0054)

**Files:**
- Create: `backend/migrations/versions/0054_endpoint_trigger.py`
- Modify: `backend/src/dewpoint/core/models/ingress.py` (`WebhookEndpoint`)
- Modify: `backend/tests/core/test_migration_chain.py`, `backend/tests/core/ingress/test_ingress_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: column `webhook_endpoints.trigger_key text NULL`; `WebhookEndpoint.trigger_key: Mapped[str | None]`. The
  API's role inserts it (its INSERT is table-wide) and can't update it.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/core/test_migration_chain.py`, change the head's assertion to `["0054"]`, and add at the end:

```python
def test_the_endpoint_sender_comes_after_the_samples_record() -> None:
    """Slot 0054 (4c-3a) is chained after main's head when it was written, 0045: slot numbers name ownership, not
    order."""
    assert script().get_revision("0054").down_revision == "0045"
```

In `backend/tests/core/ingress/test_ingress_schema.py`:
- In the parametrization of `test_the_api_cant_change_where_an_endpoints_events_and_ids_are`, after the case
  `({"events_pointer": "/events"}, {"events_pointer": "/items"}),`, add:
  ```python
          ({}, {"trigger_key": "demo.webhook"}),
          ({"trigger_key": "demo.webhook"}, {"trigger_key": None}),
          ({"trigger_key": "demo.webhook"}, {"trigger_key": "other.webhook"}),
  ```
- Its docstring's last sentence becomes:
  ```python
      change it: its role has no grant on `id_source`, `id_pointer`, `id_header` or `events_pointer`. Nor on
      `trigger_key`, the trigger an endpoint was made for (4c-3a ruling 1), which its settings came from."""
  ```
- In `test_the_api_still_makes_endpoints_and_changes_what_it_manages`, the docstring's first sentence becomes:
  ```python
      """The control for the test above, as the API's role: it still makes an endpoint, with where its events and their
      ids are and the trigger it's for, and changes every column the API changes (a PATCH's fields, a rotated secret,
      the byte burst a larger body limit needs, the time)."""
  ```
  its insert of the signed endpoint becomes:
  ```python
              text("insert into webhook_endpoints (id, tenant_id, name, created_by, auth_kind, hmac_secret, "
                   "signature_header, timestamp_header, id_source, id_pointer, events_pointer, dedupe_key, trigger_key) "
                   "values (:i, :t, 'signed', :u, 'hmac', 'sealed', 'x-signature', 'x-timestamp', 'pointer', '/id', "
                   "'/events', 'sealed-dedupe-key', 'demo.webhook')"),
  ```
  and after its assertion on `made["id_source"], made["id_pointer"], made["events_pointer"]`, add:
  ```python
      assert made["trigger_key"] == "demo.webhook" and changed["trigger_key"] is None
  ```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --frozen pytest -q tests/core/test_migration_chain.py tests/core/ingress/test_ingress_schema.py`
Expected: 6 failed: the head is still `["0045"]`, no revision `0054`, and the three new cases and the control fail on
a column that doesn't exist.

- [ ] **Step 3: Write the migration and the model's column**

Create `backend/migrations/versions/0054_endpoint_trigger.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""An endpoint records the trigger it's for (4c-3a ruling 1): the key of a trigger type a synced plugin declares
(`mist.webhook`), its settings taken from that trigger when it's made; null for another sender. Like where its events
and their ids are (2b-4 ruling D10), it never changes: the API's role has no grant to update it, and still sets it on a
new endpoint (its INSERT is table-wide). A nullable column with no default: a catalog change, no rewrite.

Slot 0054 is the owner's (2026-10-10; 0050-0053 are 2b-4b's); slot numbers name ownership, not order, so it is chained
after main's head when it was written, 0045."""

import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_endpoints", sa.Column("trigger_key", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("webhook_endpoints", "trigger_key")
```

In `backend/src/dewpoint/core/models/ingress.py`, `WebhookEndpoint`'s docstring becomes:

```python
    """An endpoint (`/hooks/<id>`): its authentication, its limits, where its events' ids are, the trigger it's for, its
    rate buckets, its pending and retained counters and their quotas. Its secrets are sealed under the ingress key,
    never a tenant's."""
```

and after its `events_pointer` column, add:

```python
    trigger_key: Mapped[str | None] = mapped_column(Text)  # the trigger type it was made for; null: another sender
```

- [ ] **Step 4: Run them to see them pass**

Run: `uv run --frozen pytest -q tests/core/test_migration_chain.py tests/core/ingress/test_ingress_schema.py tests/core/test_model_schema.py`
Expected: 35 passed. The model schema test compares tables and keys, not columns: it passes either way, and is run
to see the model still matches.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/0054_endpoint_trigger.py backend/src/dewpoint/core/models/ingress.py \
  backend/tests/core/test_migration_chain.py backend/tests/core/ingress/test_ingress_schema.py
git commit -m "feat(webhooks): an endpoint records the trigger it's for (migration 0054)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: An endpoint made for a trigger

**Files:**
- Modify: `backend/src/dewpoint/apps/webhooks.py` (`_for_trigger`, `create_endpoint`, `endpoint_body`)
- Modify: `backend/src/dewpoint/apps/api/routes/webhooks.py` (`EndpointIn`, `EndpointPatch`'s docstring,
  `create_endpoint`)
- Modify: `backend/tests/apps/api/test_webhooks_api.py`

**Interfaces:**
- Consumes: `WebhookEndpoint.trigger_key` (Task 2); `registry.list_triggers(s) -> list[dict]` (each `{"plugin", "key",
  "label", "endpoint": {"auth", "events_pointer", "id_source"}, "topic_pointer", "topics"}`).
- Produces: `webhooks.create_endpoint(..., given, written: frozenset[str] = frozenset())`; `EndpointIn.trigger:
  str | None`; every endpoint answer's `"trigger": str | None`; the create audit's `details["trigger"]`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/apps/api/test_webhooks_api.py`, the imports gain (in ruff's order: `sync_installed` after
`create_app`; `FLOW` and `Plugin, Trigger` after `canonical`; `DEMO, EVENT` after `as_role`; `TESTKIT` last):

```python
from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.sdk import Plugin, Trigger
from tests.apps.api.test_trigger_types import DEMO, EVENT
from tests.support.plugins.testkit import TESTKIT
```

After `test_an_endpoint_that_isnt_one_is_refused_with_what_to_change`, add:

```python
@pytest.fixture
async def demo(admin_sessionmaker) -> None:
    """The demo plugin's trigger, `demo.webhook` (a bearer endpoint, each delivery one event), synced beside flow and
    testkit, as `dewpoint plugins sync` would."""
    async with admin_sessionmaker() as s, s.begin():
        await sync_installed(s, [FLOW, TESTKIT, DEMO])


async def test_an_endpoint_made_for_a_trigger_takes_its_settings_and_says_so(
    keyed_app, tenant, demo, owner_sessionmaker, api_settings
) -> None:
    """4c-3a ruling 1: an endpoint names the trigger type it's for and takes that trigger's endpoint settings (how it
    proves its sender, where its events and their ids are); every answer says which. Another sender's says null."""
    ctx, _ = tenant
    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx, trigger="demo.webhook")
    assert body.pop("secret").startswith("dwp_")
    assert {k: body[k] for k in ("trigger", "auth", "events_pointer", "id_source", "id_pointer", "id_header")} == {
        "trigger": "demo.webhook", "auth": "bearer", "events_pointer": None, "id_source": "none", "id_pointer": None,
        "id_header": None,
    }  # fmt: skip
    assert (await row(owner_sessionmaker, "webhook_endpoints", body["id"]))["trigger_key"] == "demo.webhook"
    other = await made(keyed_app, owner_sessionmaker, api_settings, ctx, name="other")
    assert other["trigger"] is None
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    listed = (await viewer.get(url(ctx, "/webhook-endpoints"))).json()["endpoints"]
    assert {e["id"]: e["trigger"] for e in listed} == {body["id"]: "demo.webhook", other["id"]: None}
    assert (await viewer.get(url(ctx, f"/webhook-endpoints/{body['id']}"))).json()["trigger"] == "demo.webhook"
    made_audits = await audited(owner_sessionmaker, "webhook_endpoint.create")
    assert [a["details"]["trigger"] for a in made_audits] == ["demo.webhook", None]


async def test_an_endpoint_keeps_its_trigger_when_a_plugin_stops_declaring_it(
    keyed_app, tenant, demo, admin_sessionmaker, owner_sessionmaker, api_settings
) -> None:
    """A plugin's later version that no longer declares a trigger: an endpoint made for it keeps the key it was made
    for (the editor says its sender is unknown), and no new endpoint can name it."""
    ctx, _ = tenant
    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx, trigger="demo.webhook")
    later = Plugin(name="demo", version="1.0.1", nodes=(), connection_types=(),
                   triggers=(Trigger("demo.other", "Demo other", "bearer", "/topic", {"a": EVENT}),))  # fmt: skip
    async with admin_sessionmaker() as s, s.begin():
        await sync_installed(s, [FLOW, TESTKIT, later])
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    assert (await editor.get(url(ctx, f"/webhook-endpoints/{body['id']}"))).json()["trigger"] == "demo.webhook"
    refused = await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "x", "trigger": "demo.webhook"})
    assert (refused.status_code, refused.json()) == (422, {"error": "endpoint_invalid", "fields": ["trigger"]})


async def test_an_endpoint_for_a_signed_trigger_takes_the_default_headers(
    keyed_app, tenant, admin_sessionmaker, owner_sessionmaker, api_settings
) -> None:
    """A trigger whose endpoint is signed (`hmac`): the endpoint is, with the default signature and timestamp headers,
    its secret an HMAC secret sealed under the ingress key, shown once."""
    signed = Plugin(name="demo", version="1.0.0", nodes=(), connection_types=(),
                    triggers=(Trigger("demo.signed", "Demo signed", "hmac", "/topic", {"a": EVENT}),))  # fmt: skip
    async with admin_sessionmaker() as s, s.begin():
        await sync_installed(s, [FLOW, TESTKIT, signed])
    ctx, _ = tenant
    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx, trigger="demo.signed")
    assert {k: body[k] for k in ("trigger", "auth", "signature_header", "timestamp_header")} == {
        "trigger": "demo.signed", "auth": "hmac", "signature_header": "x-dewpoint-signature",
        "timestamp_header": "x-dewpoint-timestamp",
    }  # fmt: skip
    stored = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
    assert stored["bearer_digest"] is None
    assert KEY.open(HMAC_SECRET, body["id"], stored["hmac_secret"]).decode() == body["secret"]


@pytest.mark.parametrize(
    ("given", "fields"),
    [
        ({"trigger": "demo.missing"}, ["trigger"]),
        ({"trigger": "demo.webhook", "auth": "hmac"}, ["auth"]),
        ({"trigger": "demo.webhook", "events_pointer": "/events"}, ["events_pointer"]),
        ({"trigger": "demo.webhook", "id_source": "pointer", "id_pointer": "/id"}, ["id_pointer", "id_source"]),
        ({"trigger": "demo.webhook", "id_source": "header", "id_header": "x-event-id"}, ["id_header", "id_source"]),
    ],
)
async def test_an_endpoint_for_a_trigger_refuses_what_the_trigger_decides_otherwise(
    keyed_app, tenant, demo, owner_sessionmaker, api_settings, given, fields
) -> None:
    """A trigger that no synced plugin declares is refused, and so is a setting the request writes that its trigger
    decides otherwise: nothing is made. Writing what the trigger decides is no clash."""
    ctx, _ = tenant
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "x"} | given)
    assert (answer.status_code, answer.json()) == (422, {"error": "endpoint_invalid", "fields": fields})
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from webhook_endpoints"))).scalar_one() == 0
    agreeing = {"name": "x", "trigger": "demo.webhook", "auth": "bearer", "id_source": "none"}
    same = await editor.post(url(ctx, "/webhook-endpoints"), json=agreeing)
    assert same.status_code == 201, same.text
```

In `test_an_endpoint_is_updated_and_disabled_but_never_its_identity`, the PATCHes it expects refused gain the
trigger:

```python
    for refused in ({"id_source": "pointer", "id_pointer": "/id"}, {"auth": "hmac"}, {"name": None},
                    {"events_pointer": "/events"}, {"events_pointer": None}, {"trigger": "demo.webhook"},
                    {"trigger": None}):  # fmt: skip
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --frozen pytest -q tests/apps/api/test_webhooks_api.py`
Expected: 8 failed: the three new tests and the refusal test's five cases. `EndpointIn` forbids the unknown
`trigger`, so a create is refused as malformed (422, not `endpoint_invalid`), and `made` asserts a 201. The PATCH
test already passes (`EndpointPatch` forbids unknown keys): it stays as the guard that it keeps doing so.

- [ ] **Step 3: Make an endpoint for a trigger**

In `backend/src/dewpoint/apps/webhooks.py`, import the registry after the workflows model:

```python
from dewpoint.core.plugins import registry
```

Before `create_endpoint`, add:

```python
async def _for_trigger(s: AsyncSession, given: Mapping[str, Any], written: frozenset[str]) -> Mapping[str, Any]:
    """`given`, with what its trigger's endpoint decides (plugins-3 D17; 4c-3a ruling 1): how it proves its sender and
    where its events and their ids are. The trigger must be one a synced plugin declares, and a field the request wrote
    must say what the trigger does. Raises WebhookRefusedError."""
    named = given.get("trigger")
    if named is None:
        return given
    declared = {t.get("key"): t for t in await registry.list_triggers(s)}
    if named not in declared:
        raise WebhookRefusedError(422, {"error": "endpoint_invalid", "fields": ["trigger"]})
    endpoint = declared[named]["endpoint"]
    decided = {"auth": endpoint["auth"], "events_pointer": endpoint.get("events_pointer"),
               "id_source": endpoint.get("id_source", "none"), "id_pointer": None, "id_header": None}  # fmt: skip
    clashing = sorted(k for k in decided if k in written and given.get(k) != decided[k])
    if clashing:
        raise WebhookRefusedError(422, {"error": "endpoint_invalid", "fields": clashing})
    return {**given, **decided}
```

`create_endpoint`'s signature, docstring and first lines become:

```python
async def create_endpoint(
    s: AsyncSession, keyring: Keyring, key: IngressKey, *, tenant_id: uuid.UUID, actor_id: uuid.UUID,
    given: Mapping[str, Any], written: frozenset[str] = frozenset(),
) -> tuple[WebhookEndpoint, str]:  # fmt: skip
    """The endpoint and its secret, to show once. `written`: the fields the request gave, which its trigger, if it
    names one, must agree with. Raises WebhookRefusedError."""
    given = await _for_trigger(s, given, written)
    auth, id_source = given["auth"], given["id_source"]
```

In the `WebhookEndpoint(...)` it builds, the `id_header` line becomes:

```python
        id_header=given.get("id_header"), events_pointer=given.get("events_pointer"), trigger_key=given.get("trigger"),
```

and its audit's details become:

```python
    await _audit(s, tenant_id, actor_id, "webhook_endpoint.create", "webhook_endpoint", endpoint_id,
                 {"name": endpoint.name, "auth": auth, "id_source": id_source,
                  "trigger": endpoint.trigger_key})  # fmt: skip
```

In `endpoint_body`, the line holding `id_header` and `events_pointer` becomes two:

```python
        "id_header": endpoint.id_header, "events_pointer": endpoint.events_pointer, "trigger": endpoint.trigger_key,
        "path": f"/hooks/{endpoint.id}",
```

In `backend/src/dewpoint/apps/api/routes/webhooks.py`, `EndpointIn` gains, after `events_pointer`:

```python
    trigger: str | None = Field(default=None, min_length=1, max_length=64)  # a trigger type's key (4c-3a ruling 1)
```

`EndpointPatch`'s docstring becomes:

```python
    """Only the fields given change, never an endpoint's identity (how it authenticates, where its events and their ids
    are, the trigger it's for)."""
```

and the route `create_endpoint` passes what the request wrote:

```python
        endpoint, secret = await webhooks.create_endpoint(db, keyring, key, tenant_id=ctx.tenant_id,
                                                          actor_id=ctx.user.id, given=given.model_dump(),
                                                          written=frozenset(given.model_fields_set))  # fmt: skip
```

- [ ] **Step 4: Run them to see them pass**

Run: `uv run --frozen pytest -q tests/apps/api/test_webhooks_api.py tests/apps/api/test_trigger_types.py`
Expected: every test passes.

- [ ] **Step 5: Lint, types, commit**

Run: `uv run --frozen ruff format src tests && uv run --frozen ruff check src tests && uv run --frozen mypy src`
Expected: clean.

```bash
git add backend/src/dewpoint/apps/webhooks.py backend/src/dewpoint/apps/api/routes/webhooks.py \
  backend/tests/apps/api/test_webhooks_api.py
git commit -m "feat(webhooks): an endpoint made for a trigger takes its settings, and says which

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: A workflow's webhook bindings (B13)

**Files:**
- Modify: `backend/src/dewpoint/apps/webhooks.py` (`endpoint_summary`)
- Modify: `backend/src/dewpoint/apps/api/routes/webhooks.py` (`workflow_bindings`)
- Modify: `backend/tests/apps/api/test_webhooks_api.py`

**Interfaces:**
- Consumes: `webhooks.binding_body`, `WebhookEndpoint.trigger_key` (Task 2).
- Produces: `GET /api/v1/t/{tenant_id}/workflows/{workflow_id}/webhook-bindings` →
  `{"bindings": [binding_body | {"endpoint": {"id", "name", "enabled", "auth", "path", "trigger"}}]}`;
  `webhooks.endpoint_summary(endpoint) -> dict[str, object]`.

- [ ] **Step 1: Write the failing test**

In `backend/tests/apps/api/test_webhooks_api.py`, before `test_bindings_are_checked_capped_and_unique`, add:

```python
async def test_a_workflows_webhooks_are_listed_with_their_endpoints(
    keyed_app, tenant, demo, owner_sessionmaker, api_settings, api_sessionmaker, admin_sessionmaker
) -> None:
    """B13 (4c-3a ruling 2): the webhooks that start a workflow, read with `workflow.view`, each with what the Triggers
    panel shows of its endpoint, by the endpoint's name; another workflow's aren't among them. A workflow the caller's
    tenant doesn't have, unknown or another tenant's, is 404."""
    ctx, wf = tenant
    mist = await made(keyed_app, owner_sessionmaker, api_settings, ctx, name="Mist prod", trigger="demo.webhook")
    ticketing = await made(keyed_app, owner_sessionmaker, api_settings, ctx, name="Ticketing", auth="hmac")
    other = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, 'Other', "
                             "true, '{}')"), {"w": other, "t": ctx.tenant_id})  # fmt: skip
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    for endpoint, workflow, body in ((ticketing, wf, {"enabled": False}), (mist, other, {}),
                                     (mist, wf, {"filter": [{"pointer": "/topic", "value": "a"}]})):  # fmt: skip
        bound = await editor.post(url(ctx, f"/webhook-endpoints/{endpoint['id']}/bindings"),
                                  json={"workflow_id": str(workflow)} | body)  # fmt: skip
        assert bound.status_code == 201, bound.text
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    answer = await viewer.get(url(ctx, f"/workflows/{wf}/webhook-bindings"))
    assert answer.status_code == 200, answer.text
    bindings = answer.json()["bindings"]
    assert [(b["endpoint"]["name"], b["enabled"], b["filter"]) for b in bindings] == [
        ("Mist prod", True, [{"pointer": "/topic", "value": "a"}]), ("Ticketing", False, []),
    ]  # fmt: skip
    assert bindings[0]["endpoint"] == {"id": mist["id"], "name": "Mist prod", "enabled": True, "auth": "bearer",
                                       "path": f"/hooks/{mist['id']}", "trigger": "demo.webhook"}  # fmt: skip
    assert (bindings[1]["endpoint"]["auth"], bindings[1]["endpoint"]["trigger"]) == ("hmac", None)
    assert {(b["workflow_id"], b["endpoint_id"]) for b in bindings} == {(str(wf), mist["id"]),
                                                                       (str(wf), ticketing["id"])}  # fmt: skip
    _, theirs = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, OPEN_GRAPH)
    for unknown in (uuid.uuid4(), theirs):
        missing = await viewer.get(url(ctx, f"/workflows/{unknown}/webhook-bindings"))
        assert (missing.status_code, missing.json()) == (404, {"error": "not_found"})
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run --frozen pytest -q tests/apps/api/test_webhooks_api.py -k listed_with_their_endpoints`
Expected: FAIL: `assert 404 == 200` (no such route; the app answers its `not_found`).

- [ ] **Step 3: The route**

In `backend/src/dewpoint/apps/webhooks.py`, before `binding_body`, add:

```python
def endpoint_summary(endpoint: WebhookEndpoint) -> dict[str, object]:
    """What a workflow's Triggers panel shows of a binding's endpoint (B13; 4c-3a ruling 2)."""
    return {"id": str(endpoint.id), "name": endpoint.name, "enabled": endpoint.enabled, "auth": endpoint.auth_kind,
            "path": f"/hooks/{endpoint.id}", "trigger": endpoint.trigger_key}  # fmt: skip
```

In `backend/src/dewpoint/apps/api/routes/webhooks.py`, import `and_` with `select` (`from sqlalchemy import and_,
select`) and the workflow model after the ingress models:

```python
from dewpoint.core.models.workflows import Workflow
```

Before `update_binding`'s route, add:

```python
@router.get("/t/{tenant_id}/workflows/{workflow_id}/webhook-bindings")
async def workflow_bindings(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """The webhooks that start a workflow (B13; 4c-3a ruling 2), each with what its Triggers panel shows of the
    endpoint, by the endpoint's name."""
    if await db.get(Workflow, workflow_id) is None:  # row-level security: the caller's tenant's only
        raise HTTPException(404, detail={"error": "not_found"})
    found = await db.execute(
        select(TriggerBinding, WebhookEndpoint)
        .join(WebhookEndpoint, and_(WebhookEndpoint.id == TriggerBinding.endpoint_id,
                                    WebhookEndpoint.tenant_id == TriggerBinding.tenant_id))
        .where(TriggerBinding.workflow_id == workflow_id)
        .order_by(WebhookEndpoint.name, WebhookEndpoint.id)
    )  # fmt: skip
    return {"bindings": [webhooks.binding_body(b) | {"endpoint": webhooks.endpoint_summary(e)} for b, e in found.all()]}
```

- [ ] **Step 4: Run them to see them pass**

Run: `uv run --frozen pytest -q tests/apps/api/test_webhooks_api.py`
Expected: every test passes.

- [ ] **Step 5: Lint, types, commit**

Run ruff (format and check) and mypy as "How to run things" says.
Expected: clean.

```bash
git add backend/src/dewpoint/apps/webhooks.py backend/src/dewpoint/apps/api/routes/webhooks.py \
  backend/tests/apps/api/test_webhooks_api.py
git commit -m "feat(webhooks): a workflow's webhook bindings, with their endpoints (B13)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4c-3a, milestone 1 (date)` to the ledger: the tasks' commits, each test run's result, any mid-slice
ruling. Commit it (`docs(editor-4): 4c-3a milestone 1`).

---

# Milestone 2 — schedules and the list

### Task 5: What a schedule's sync proves

**Files:**
- Modify: `backend/src/dewpoint/apps/schedules.py` (`Accounting`, `accounting`, `body`)
- Modify: `backend/tests/apps/api/test_schedules_api.py`

**Interfaces:**
- Consumes: `ScheduleIncarnation` (`backfilled`, `unpause_sent_at`, `landed_paused`), read by `accounting()`.
- Produces: `Accounting.never_unpaused: bool`; the schedule answer's `"sync_error_at": str | None` and
  `"never_unpaused": bool`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/apps/api/test_schedules_api.py`, import `from datetime import UTC, datetime` after `import uuid`, and
add at the end:

```python
async def incarnation(owner: Any, ctx: Any, schedule_id: str, number: int, **columns: Any) -> None:
    """A Temporal schedule id the sync recorded for the schedule, as `schedule_incarnations` holds one."""
    values = {"temporal_id": f"t-{schedule_id}-{number}", "tenant_id": ctx.tenant_id, "schedule_id": schedule_id,
              "number": number, "generation": 1} | columns  # fmt: skip
    async with owner() as s, s.begin():
        await s.execute(text(f"insert into schedule_incarnations ({', '.join(values)}) "  # noqa: S608
                             f"values ({', '.join(':' + k for k in values)})"), values)  # fmt: skip


async def test_a_schedule_says_when_its_sync_failed_and_that_nothing_ever_unpaused_it(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """4c-3a ruling 6: the answer says when the sync last failed (an edit doesn't clear a failure, so the editor tells
    an earlier one from the latest edit's), and that nothing ever unpaused it: created paused, only the sync unpauses
    it, recording that first, so with no unpause recorded it has never fired."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    made = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
    assert (made["sync_error"], made["sync_error_at"], made["never_unpaused"]) == (None, None, True)
    await incarnation(owner_sessionmaker, ctx, made["id"], 1)  # recorded, created paused, its unpause not yet sent
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update schedules set sync_error = 'temporal_refused', sync_error_at = now() "
                             "where id = :i"), {"i": made["id"]})  # fmt: skip
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    got = (await viewer.get(schedule_url(ctx, made["id"]))).json()
    stored = await row(owner_sessionmaker, made["id"])
    assert (got["sync_error"], got["sync_error_at"], got["never_unpaused"]) == (
        "temporal_refused", stored["sync_error_at"].isoformat(), True,
    )  # fmt: skip
    listed = (await viewer.get(schedules_url(ctx, wf))).json()["schedules"]
    assert [(s["sync_error_at"], s["never_unpaused"]) for s in listed] == [(stored["sync_error_at"].isoformat(), True)]


@pytest.mark.parametrize(
    "evidence",
    [{"unpause_sent_at": datetime(2026, 10, 10, 8, tzinfo=UTC)}, {"landed_paused": False}, {"backfilled": True}],
    ids=["unpause-sent", "seen-unpaused", "from-before-2b-4a"],
)
async def test_a_schedule_that_may_have_been_unpaused_never_says_otherwise(
    keyed_app, workflow, owner_sessionmaker, api_settings, evidence: dict[str, Any]
) -> None:
    """An unpause sent, an incarnation seen unpaused, or one from before 2b-4a (whose unpauses nobody recorded), on any
    of its incarnations: it may have fired, so `never_unpaused` is false."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    made = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
    await incarnation(owner_sessionmaker, ctx, made["id"], 0, **evidence)
    await incarnation(owner_sessionmaker, ctx, made["id"], 1)
    assert (await editor.get(schedule_url(ctx, made["id"]))).json()["never_unpaused"] is False
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --frozen pytest -q tests/apps/api/test_schedules_api.py`
Expected: 4 failed, on `KeyError: 'sync_error_at'` and `KeyError: 'never_unpaused'`.

- [ ] **Step 3: The two fields**

In `backend/src/dewpoint/apps/schedules.py`, `Accounting` gains, after `uncounted`:

```python
    # Whether nothing ever unpaused it (4c-3a ruling 6): its incarnations, read here for its waits, record an unpause
    # before it's sent; one seen unpaused, or one from before 2b-4a, whose unpauses nobody recorded, may have fired.
    never_unpaused: bool = True
```

`accounting()`'s return becomes:

```python
    unpaused = any(i.backfilled or i.unpause_sent_at is not None or i.landed_paused is False for i in ids)
    return Accounting([span for _, span in sorted(spans, key=lambda pair: pair[0])], never_unpaused=not unpaused)
```

and `body()` gains, after `"sync_error"`:

```python
        # when it last failed: an edit doesn't clear a failure, so an earlier one shows beside the latest edit's time
        "sync_error_at": schedule.sync_error_at.isoformat() if schedule.sync_error_at else None,
        "never_unpaused": accounted.never_unpaused,  # never fired: only the sync unpauses, recording it first
```

- [ ] **Step 4: Run them to see them pass**

Run: `uv run --frozen pytest -q tests/apps/api/test_schedules_api.py tests/apps/test_schedules.py tests/apps/test_schedules_legacy.py`
Expected: every test passes.

- [ ] **Step 5: Lint, types, commit**

Run ruff (format and check) and mypy as "How to run things" says.
Expected: clean.

```bash
git add backend/src/dewpoint/apps/schedules.py backend/tests/apps/api/test_schedules_api.py
git commit -m "feat(schedules): a schedule says when its sync failed, and that nothing ever unpaused it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The list says what starts each workflow, and when a schedule failed to sync

**Files:**
- Modify: `backend/src/dewpoint/apps/workflow_summary.py` (`TRIGGERS`, `TriggerStats`, `trigger_stats`, `attention`)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`_summaries`)
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`TriggersOut`; `WorkflowOut.triggers`, its attention literal)
- Modify: `backend/tests/apps/api/test_workflow_summary.py`

**Interfaces:**
- Consumes: `schedules` (`workflow_id`, `enabled`, `sync_error`, `deleted_at`) through `schedules_workflow`;
  `trigger_bindings` through `trigger_bindings_one`; `workflow_ops.declares_csv(graph) -> bool`.
- Produces: `workflow_summary.TriggerStats(schedules: int, schedules_enabled: int, sync_failed: bool,
  webhook_bindings: int)`; `trigger_stats(s, tenant_id, ids) -> dict[uuid.UUID, TriggerStats]`; `attention(...,
  sync_failed: bool = False)`; every workflow answer's `triggers` and `needs_attention`'s `"schedule_sync_failed"`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/apps/api/test_workflow_summary.py`, import `from tests.apps.test_admission import CSV_GRAPH` after
`session_client`'s import, and widen what the reads test counts:

```python
WORKFLOW_TABLES = ("workflows", "workflow_versions", "runs", "node_type_versions", "cel_profiles", "schedules",
                   "trigger_bindings")  # fmt: skip
```

`published` takes a graph, and two helpers go before it:

```python
async def add_schedule(owner, tid, wid, **columns) -> uuid.UUID:
    """A schedule row as the API writes one: a live one's input sealed (the list never reads it), a tombstone's
    cleared."""
    sid = uuid.uuid4()
    values = {"id": sid, "tenant_id": tid, "workflow_id": wid, "cron": "0 9 * * *", "mode": "live",
              "input": None if columns.get("deleted_at") else b"sealed"} | columns  # fmt: skip
    async with owner() as s, s.begin():
        values["created_by"] = (await s.execute(text("select user_id from memberships where tenant_id = :t"),
                                                {"t": tid})).scalar_one()  # fmt: skip
        await s.execute(text(f"insert into schedules ({', '.join(values)}) "  # noqa: S608
                             f"values ({', '.join(':' + k for k in values)})"), values)  # fmt: skip
    return sid


async def add_binding(owner, tid, wid, *, enabled=True) -> None:
    """A webhook binding of the workflow, on an endpoint of its own."""
    eid = uuid.uuid4()
    async with owner() as s, s.begin():
        user = (await s.execute(text("select user_id from memberships where tenant_id = :t"), {"t": tid})).scalar_one()
        await s.execute(
            text("insert into webhook_endpoints (id, tenant_id, name, created_by, auth_kind, bearer_digest, dedupe_key)"
                 " values (:e, :t, 'hooks', :u, 'bearer', 'digest', 'sealed')"),
            {"e": eid, "t": tid, "u": user},
        )  # fmt: skip
        await s.execute(
            text("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, enabled, created_by) "
                 "values (:i, :t, :e, :w, :on, :u)"),
            {"i": uuid.uuid4(), "t": tid, "e": eid, "w": wid, "on": enabled, "u": user},
        )  # fmt: skip


async def published(c, tid, graph=GRAPH) -> tuple[str, str]:
    wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": f"W {uuid.uuid4().hex[:6]}", "draft": graph})).json()
```

(the rest of `published` is unchanged). `test_the_statements_filter_by_tenant_themselves` covers the new statement
too; it becomes:

```python
async def test_the_statements_filter_by_tenant_themselves(app, owner_sessionmaker, api_settings) -> None:
    """Row-level security keeps another tenant's runs and triggers from the API's role; the statements also filter by
    tenant themselves. With row-level security out of the way (the owner's session), asked for this tenant about
    another tenant's workflow, they find no run or trigger of it, while the rows are there for its own tenant."""
    from dewpoint.apps import workflow_summary

    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    other, otid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c, other:
        owid, ovid = await published(other, otid)
        await add_run(owner_sessionmaker, otid, owid, ovid, status="failed")
        await add_schedule(owner_sessionmaker, otid, owid, sync_error="sync_failed")
        await add_binding(owner_sessionmaker, otid, owid)
        assert (await c.get(f"/api/v1/t/{tid}/workflows")).json() == []
    theirs = uuid.UUID(owid)
    async with owner_sessionmaker() as s:
        mine = (await workflow_summary.run_stats(s, tid, [theirs]))[theirs]
        found = (await workflow_summary.run_stats(s, otid, [theirs]))[theirs]
        my_triggers = (await workflow_summary.trigger_stats(s, tid, [theirs]))[theirs]
        their_triggers = (await workflow_summary.trigger_stats(s, otid, [theirs]))[theirs]
    assert (mine.last_live, mine.live_24h) == (None, 0)
    assert my_triggers == workflow_summary.TriggerStats(0, 0, False, 0)
    # The rows are there: the tenant filter alone kept them out.
    assert found.last_live is not None and found.last_live.status == "failed"
    assert their_triggers == workflow_summary.TriggerStats(1, 1, True, 1)
```

Before `test_the_lists_reads_dont_grow_with_its_workflows`, add:

```python
async def test_the_list_says_what_starts_each_workflow(app, owner_sessionmaker, api_settings) -> None:
    """4c-3a ruling 3: each row counts its live schedules (a deleted one's tombstone left out) and how many are on, and
    its webhook bindings, and says whether its active version takes a CSV file (never its draft); a workflow never
    published has none."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        busy, _ = await published(c, tid)
        await add_schedule(owner_sessionmaker, tid, busy)
        await add_schedule(owner_sessionmaker, tid, busy, enabled=False)
        await add_schedule(owner_sessionmaker, tid, busy, deleted_at=datetime.now(UTC))
        await add_binding(owner_sessionmaker, tid, busy)
        await add_binding(owner_sessionmaker, tid, busy, enabled=False)
        upload, _ = await published(c, tid, CSV_GRAPH)
        draft = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Draft", "draft": GRAPH})).json()["id"]
        # A draft that would take a CSV file: the column says what the active version does, until it's published.
        saved = await c.put(f"/api/v1/t/{tid}/workflows/{busy}/draft", json=CSV_GRAPH, headers={"If-Match": "1"})
        assert saved.status_code == 200, saved.text
        rows = {w["id"]: w for w in (await c.get(f"/api/v1/t/{tid}/workflows")).json()}
        one = (await c.get(f"/api/v1/t/{tid}/workflows/{busy}")).json()
    assert rows[busy]["triggers"] == one["triggers"] == {
        "schedules": 2, "schedules_enabled": 1, "webhook_bindings": 2, "csv": False,
    }  # fmt: skip
    assert rows[upload]["triggers"] == {"schedules": 0, "schedules_enabled": 0, "webhook_bindings": 0, "csv": True}
    assert rows[draft]["triggers"] == {"schedules": 0, "schedules_enabled": 0, "webhook_bindings": 0, "csv": False}


async def test_a_schedule_that_failed_to_sync_needs_attention(app, owner_sessionmaker, api_settings) -> None:
    """4c-3a ruling 4 (ruling 74's "sync errors join with 4c"): a live schedule whose last sync failed, on or off,
    raises `schedule_sync_failed`; a deleted one's tombstone doesn't, and a sync that succeeds since clears it."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        failing, _ = await published(c, tid)
        sid = await add_schedule(owner_sessionmaker, tid, failing, enabled=False, sync_error="temporal_refused",
                                 sync_error_at=datetime.now(UTC))  # fmt: skip
        gone, _ = await published(c, tid)
        await add_schedule(owner_sessionmaker, tid, gone, sync_error="sync_failed", sync_error_at=datetime.now(UTC),
                           deleted_at=datetime.now(UTC))  # fmt: skip
        rows = {w["id"]: w for w in (await c.get(f"/api/v1/t/{tid}/workflows")).json()}
        assert rows[failing]["needs_attention"] == ["schedule_sync_failed"]
        assert rows[gone]["needs_attention"] == []
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update schedules set sync_error = null, sync_error_at = null where id = :i"),
                            {"i": sid})  # fmt: skip
        assert (await c.get(f"/api/v1/t/{tid}/workflows/{failing}")).json()["needs_attention"] == []
```

and in `test_the_lists_reads_dont_grow_with_its_workflows`, the bound becomes:

```python
    assert few == many <= 7  # workflows, active versions, two lifecycle reads at most, last runs, counts, triggers
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --frozen pytest -q tests/apps/api/test_workflow_summary.py`
Expected: 3 failed: `KeyError: 'triggers'`, `assert [] == ['schedule_sync_failed']`, and `trigger_stats` missing from
`workflow_summary`.

- [ ] **Step 3: The triggers' read, the attention reason, the answer**

In `backend/src/dewpoint/apps/workflow_summary.py`, the module docstring's first sentence names the triggers:

```python
"""What the workflows list shows of each workflow beyond its row (sub-project 4, B3): its last live root run and, apart,
its last simulated one; its root runs in the last 24 hours, live and simulated apart; whether its draft differs from
its active version; what starts it (4c-3a ruling 3); and why it needs attention. Live runs alone drive attention (4b
ruling 7): a simulation is a test, and a later successful one says nothing about the live failure before it."""
```

After `COUNTS_24H`, add:

```python
# Each workflow's triggers, in one statement for every workflow (4c-3a ruling 3): its live schedules (a deleted one's
# tombstone left out), how many are on and whether any last failed to sync (ruling 74; 4c-3a ruling 4), from
# `schedules_workflow`; and its webhook bindings, from `trigger_bindings_one`, whose tenant leads.
TRIGGERS = text(
    "select w.id as workflow_id, coalesce(s.live, 0) as schedules, coalesce(s.on_, 0) as schedules_enabled,"
    " coalesce(s.failed, 0) > 0 as sync_failed, coalesce(b.bound, 0) as webhook_bindings"
    " from unnest(cast(:ids as uuid[])) as w(id)"
    " left join (select workflow_id, count(*) as live, count(*) filter (where enabled) as on_,"
    " count(*) filter (where sync_error is not null) as failed from schedules"
    " where tenant_id = :tenant and workflow_id = any(cast(:ids as uuid[])) and deleted_at is null"
    " group by workflow_id) as s on s.workflow_id = w.id"
    " left join (select workflow_id, count(*) as bound from trigger_bindings"
    " where tenant_id = :tenant and workflow_id = any(cast(:ids as uuid[])) group by workflow_id) as b"
    " on b.workflow_id = w.id"
)
```

and replace `attention` with:

```python
@dataclass(frozen=True)
class TriggerStats:
    schedules: int  # live: a deleted one's tombstone left out
    schedules_enabled: int
    sync_failed: bool  # a live schedule's last sync failed
    webhook_bindings: int


async def trigger_stats(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, TriggerStats]:
    """Each workflow's schedules and webhook bindings, in one statement for any number of workflows."""
    ids = sorted(set(workflow_ids), key=str)
    if not ids:
        return {}
    found = await s.execute(TRIGGERS, {"tenant": tenant_id, "ids": ids})
    return {
        r.workflow_id: TriggerStats(
            int(r.schedules), int(r.schedules_enabled), bool(r.sync_failed), int(r.webhook_bindings)
        )
        for r in found
    }


def attention(stats: RunStats, *, published: bool, blocked: Sequence[str], sync_failed: bool = False) -> list[str]:
    """Why a workflow needs attention: its last live root run failed or ran out of time, its active version can't
    run, or a live schedule's last sync failed (ruling 74; 4c-3a ruling 4). Simulations never count (4b ruling 7)."""
    out: list[str] = []
    if stats.last_live is not None and stats.last_live.status in ATTENTION_STATUSES:
        out.append("last_run_failed")
    if published and blocked:
        out.append("not_executable")
    if sync_failed:
        out.append("schedule_sync_failed")
    return out
```

In `backend/src/dewpoint/apps/api/routes/workflows.py`, `_summaries`:
- its docstring ends "…the last runs and the 24-hour counts, and the triggers, each read once for all.";
- after `stats = await workflow_summary.run_stats(db, tenant_id, ids)`, add
  `triggers = await workflow_summary.trigger_stats(db, tenant_id, ids)`;
- `runs = stats[wf.id]` becomes `runs, starts = stats[wf.id], triggers[wf.id]`;
- the row's `needs_attention` entry becomes:

```python
                "triggers": {
                    "schedules": starts.schedules,
                    "schedules_enabled": starts.schedules_enabled,
                    "webhook_bindings": starts.webhook_bindings,
                    "csv": active is not None and workflow_ops.declares_csv(active.graph),
                },
                "needs_attention": workflow_summary.attention(
                    runs, published=active is not None, blocked=stops, sync_failed=starts.sync_failed
                ),
```

(`active` is a whole `WorkflowVersion`, its `graph` already read by `service.active_versions`: no extra read.)

In `backend/src/dewpoint/apps/api/responses.py`, before `WorkflowOut`, add:

```python
class TriggersOut(_Answer):
    """What starts a workflow besides a person (4c-3a ruling 3): by hand is always possible once it's published."""

    schedules: int  # its live schedules: a deleted one's tombstone left out
    schedules_enabled: int
    webhook_bindings: int
    csv: bool  # its active version takes a CSV file: it's started by hand, with one
```

and `WorkflowOut`'s last two fields become:

```python
    triggers: TriggersOut
    needs_attention: list[Literal["last_run_failed", "not_executable", "schedule_sync_failed"]]
```

(after `runs_24h`, which stays).

- [ ] **Step 4: Run them to see them pass**

Run: `uv run --frozen pytest -q tests/apps/api/test_workflow_summary.py tests/apps/test_workflow_summary.py tests/apps/api/test_workflows.py`
Expected: every test passes.

- [ ] **Step 5: Lint, types, commit**

Run ruff (format and check) and mypy as "How to run things" says.
Expected: clean.

```bash
git add backend/src/dewpoint/apps/workflow_summary.py backend/src/dewpoint/apps/api/routes/workflows.py \
  backend/src/dewpoint/apps/api/responses.py backend/tests/apps/api/test_workflow_summary.py
git commit -m "feat(workflows): the list says what starts each workflow, and when a schedule failed to sync

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: A draft that would break live schedules is said so

**Files:**
- Create: `backend/src/dewpoint/apps/schedule_checks.py`
- Create: `backend/tests/apps/test_schedule_checks.py`, `backend/tests/apps/api/test_schedule_checks_api.py`
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`validate_draft`, `publish`)
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`ScheduleBreakOut`, `ValidationOut.schedule_breaks`)

**Interfaces:**
- Consumes: `schedules.INPUT_PURPOSE`; `ClaimCipher(keys, purpose=…).open(tenant_id, claim_id, blob) -> bytes`;
  `key_unreadable(e) -> bool`; `get_keys(request) -> KeySource` (`routes/run_requests.py`);
  `Graph.settings.input_schema`, `Graph.settings.csv`; `workflow_ops.declares_csv`;
  `engine.runtime.projection.location(path, schema) -> str` (a place as the schema declares it, data keys as `*`);
  `engine.schema_refs.SCHEMA_ONE`, `SCHEMA_LIST`, `SCHEMA_MAP` (the keywords whose values are schemas);
  jsonschema's `Draft202012Validator` (its `VALIDATORS` and lazy `descend`), `validators.extend` and
  `ValidationError` (`validator`, `validator_value`, `instance`, `absolute_path`): check them in the installed 4.26
  before relying on them: `_keywords.anyOf`'s `list(…)` of each branch's errors, and `evolve()`'s
  `validator_for(schema, default=cls)`, which picks a subschema's validator by its `$schema`.
- Produces: `schedule_checks.shape(input_schema, *, takes_csv) -> Shape`; `Shape.check(value) -> Checked(reasons:
  list[str], more: bool)` and `Shape.partial: frozenset[str]`; `PARTIAL` (the structure the check doesn't evaluate)
  and `DIALECT` (the check's own `$schema`);
  `Budget(steps)` and `Exhausted` (every keyword the check evaluates spends a step: `Shape.budget`);
  `checked_all(input_schema, takes_csv, opened) -> (partial, [(schedule_id, Checked)], unchecked)`, run in a worker
  thread; `read_schedules(s, workflow_id) -> Read(rows: list[tuple[uuid.UUID, bytes | None]], live: int)`;
  `Breaks(refused: list[tuple[uuid.UUID, Checked]], unchecked: int, partial: frozenset[str])`; `breaks(s, keys,
  tenant_id, workflow_id, *, input_schema, takes_csv) -> Breaks`; `warnings(found, *, takes_csv) -> list[Diagnostic]`;
  `checkable(diagnostics) -> bool`; the budgets `MAX_CHECKED`, `MAX_INPUT_BYTES`, `MAX_STEPS`, `MAX_ERRORS`,
  `MAX_REASONS`, `MAX_REASON_CHARS`; the texts `CSV`, `REFUSED`, `PARTLY`, `UNCHECKED`; validate's `schedule_breaks:
  [{"schedule_id", "reasons", "more"}]`; the warnings `schedule.input_refused`, `schedule.partly_checked`,
  `schedule.unchecked`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/apps/test_schedule_checks.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Whether a stored schedule input would fit a draft's input, by its shape alone (4c-3a ruling 7). The draft's input is
checked as written, by JSON Schema's own validator extended to evaluate only structure: the keywords that test a
value's content hold for every value, `oneOf` is evaluated as `anyOf`, and the structure a shape can't keep (`not`,
`if`, …) holds and is named. So the check accepts every value the draft does, nested fields, references and `allOf`
included. Never a value's content: a draft's `maximum` or `maxLength` against a stored value would let whoever
validates learn a sensitive value a bit at a time."""

import itertools
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from dewpoint.apps import schedule_checks
from dewpoint.apps.schedule_checks import CSV, Checked, Exhausted, Shape, checked_all, shape

SECRET = "t0ken-value-1"
STORED = {"token": SECRET, "site": "a", "floor": 2, "address": {"city": "Paris"}, "tags": ["a", "b"]}


def schema(properties: dict[str, Any], **rest: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties} | rest


@pytest.mark.parametrize(
    ("input_schema", "reasons"),
    [
        (schema({"site": {"type": "string"}, "area": {"type": "string"}}, required=["site", "area"]),
         ["`area` is required now."]),
        (schema({"address": {"type": "object", "properties": {"zip": {"type": "string"}}, "required": ["zip"]}}),
         ["`address.zip` is required now."]),
        (schema({"site": {"type": "integer"}, "floor": {"type": "string"}}),
         ["`floor` must be text now.", "`site` must be a whole number now."]),
        (schema({"site": {"type": ["integer", "null"]}}), ["`site` must be a whole number or null now."]),
        ({"type": "object", "properties": {"floor": {"$ref": "#/$defs/label"}}, "$defs": {"label": {"type": "string"}}},
         ["`floor` must be text now."]),
        ({"type": "object", "allOf": [{"required": ["area"]}, {"properties": {"site": {"type": "boolean"}}}]},
         ["`area` is required now.", "`site` must be yes or no now."]),
        (schema({"tags": {"type": "array", "items": {"type": "integer"}}}),
         ["`tags.0` must be a whole number now.", "`tags.1` must be a whole number now."]),
        (schema({"floor": {"anyOf": [{"type": "string"}, {"type": "boolean"}]}}),
         ["`floor` fits none of the shapes this input allows."]),
        (schema({"token": {"type": "string"}}, additionalProperties=False),
         ["It has a field this input no longer allows."]),
        (schema({"address": {"type": "object", "properties": {}, "additionalProperties": False}}),
         ["`address` has a field this input no longer allows."]),
        (schema({"floor": {"type": "integer"}}, dependentRequired={"site": ["area"]}),
         ["`area` is required now, beside `site`."]),
        (schema({"floor": {"type": "integer"}}, required=["floor"]), []),
        (schema({"floor": {"type": "number"}}), []),
        (schema({"token": {"type": "string", "x-sensitive": True, "maxLength": 3, "minLength": 99}}), []),
        (schema({"floor": {"type": "integer", "maximum": 1, "multipleOf": 7, "const": 5, "enum": [9]},
                 "site": {"type": "string", "format": "email", "minLength": 40}}, minProperties=99), []),
        ({"type": "object"}, []),
    ],
    ids=["required", "nested-required", "type", "type-list", "reference", "all-of", "items", "any-of",
         "no-longer-allowed", "nested-no-longer-allowed", "dependent-required", "fits", "number-takes-an-integer",
         "sensitive-length", "value-constraints", "open"],
)  # fmt: skip
def test_a_stored_input_is_checked_by_its_shape(input_schema: dict[str, Any], reasons: list[str]) -> None:
    found = shape(input_schema, takes_csv=False)
    assert found.check(STORED) == Checked(reasons, more=False) and found.partial == frozenset()


def test_an_integral_number_is_a_whole_number() -> None:
    """As JSON Schema says it, and admission's validator with it: `2.0` is an integer; `2.5` and `true` aren't."""
    whole = shape(schema({"floor": {"type": "integer"}}), takes_csv=False)
    assert [whole.check({"floor": v}).reasons for v in (2.0, 0.0, 2)] == [[], [], []]
    assert (
        whole.check({"floor": 2.5}).reasons
        == whole.check({"floor": True}).reasons
        == ["`floor` must be a whole number now."]
    )


def test_a_reason_never_holds_a_value_or_a_stored_name() -> None:
    """The reasons name the draft's own fields, never the stored input's: a field the draft no longer allows is
    counted, not named, and a key the data supplied shows as `*`."""
    stored = STORED | {"secret-name": {"x": 1}}
    found = shape(schema({"site": {"type": "integer"}}, additionalProperties={"required": ["y"]},
                         required=["site", "x"]), takes_csv=False).check(stored).reasons  # fmt: skip
    assert found == ["`*.y` is required now.", "`site` must be a whole number now.", "`x` is required now."]
    assert not any(word in r for r in found for word in (SECRET, "secret-name", "Paris", "token", "address"))


@pytest.mark.parametrize(
    ("input_schema", "partial"),
    [
        (schema({"kind": {"oneOf": [{"const": "a"}, {"const": "b"}]}}), {"oneOf"}),
        (schema({"site": {"type": "string"}}, **{"not": {"required": ["site"]}}), {"not"}),
        (schema({}, **{"if": {"required": ["a"]}, "then": {"required": ["b"]}}), {"if", "then"}),
        (schema({}, propertyNames={"maxLength": 2}, unevaluatedProperties=False), {"propertyNames",
                                                                                   "unevaluatedProperties"}),
        (schema({"tags": {"type": "array", "contains": {"const": "x"}}}), {"contains"}),
    ],
    ids=["one-of", "not", "if-then", "names-and-unevaluated", "contains"],
)  # fmt: skip
def test_structure_the_shape_cant_keep_is_named_and_never_refuses(input_schema: dict[str, Any],
                                                                    partial: set[str]) -> None:  # fmt: skip
    """What the shape can't keep is dropped (or, for `oneOf`, read as `anyOf`), so the check widens and never refuses
    what the draft accepts; and it's named, so validate can say the schedules were checked in part."""
    found = shape(input_schema, takes_csv=False)
    assert found.partial == frozenset(partial) and found.check(STORED | {"kind": "a"}) == Checked([], more=False)


def test_an_input_that_takes_a_csv_file_fits_no_schedule() -> None:
    """Its rows come from an upload only (engine 2b spec §8.1): a schedule can't give them, whatever its input."""
    assert shape({"type": "object"}, takes_csv=True).check(STORED) == Checked([CSV], more=False)


def test_a_stored_input_is_read_within_its_budgets() -> None:
    """The review of revision 2: a 400 KB input whose 20,000 items all broke the draft's new item type gave 20,000
    reasons. The check reads a stored input's errors lazily, stops at `MAX_ERRORS` read or `MAX_REASONS` distinct
    reasons kept, and says it stopped (`more`)."""
    found = shape(schema({"tags": {"type": "array", "items": {"type": "integer"}}}), takes_csv=False)
    checked = found.check({"tags": ["a"] * 20_000})
    assert checked.more is True and len(checked.reasons) == schedule_checks.MAX_REASONS
    assert checked.reasons[0] == "`tags.0` must be a whole number now."


def test_a_union_is_tried_branch_by_branch_up_to_a_first_error() -> None:
    """The review of revision 3: JSON Schema's own `anyOf` builds every error of every failing branch before it
    yields one (three branches over 20,000 items: 60,000 errors). The check's `anyOf` tries each branch up to its
    first error and keeps none of them: it never names them."""
    union = {"anyOf": [{"items": {"type": "integer"}}, {"items": {"type": "boolean"}}, {"items": {"type": "null"}}]}
    found = shape(schema({"tags": {"type": "array"} | union}), takes_csv=False)
    assert found.check({"tags": ["abcdefghijklmnopq"] * 20_000}) == Checked(
        ["`tags` fits none of the shapes this input allows."]
    )
    assert schedule_checks.MAX_STEPS - found.budget.left < 50


def test_every_step_of_the_check_spends_from_one_budget(monkeypatch) -> None:
    """Every keyword the check evaluates, at any depth, spends one step of the check's budget (`MAX_STEPS`, for all
    its inputs together); when it runs out, the check stops, and what's left is counted unchecked, never refused."""
    monkeypatch.setattr(schedule_checks, "MAX_STEPS", 1_000)
    typed = schema({"tags": {"type": "array", "items": {"type": "string"}}})
    with pytest.raises(Exhausted):
        shape(typed, takes_csv=False).check({"tags": ["a"] * 5_000})
    opened = [(uuid.uuid4(), json.dumps({"tags": ["a"] * 400}).encode()) for _ in range(5)]
    partial, refused, unchecked = checked_all(typed, False, opened)
    assert (partial, refused, unchecked) == (frozenset(), [], 3)  # 2 fit in 1,000 steps; the third ran out


DIALECT = "https://json-schema.org/draft/2020-12/schema"
BRANCHES = [{"items": {"type": kind}} for kind in ("integer", "boolean", "null")]


@pytest.mark.parametrize(
    "tags",
    [{"$schema": DIALECT, "type": "array", "anyOf": BRANCHES},
     {"type": "array", "anyOf": [{"$schema": DIALECT} | branch for branch in BRANCHES]}],
    ids=["on-the-union", "in-each-branch"],
)  # fmt: skip
def test_a_dialect_declared_inside_never_leaves_the_checks_validator(tags: dict[str, Any]) -> None:
    """The review of revision 4: jsonschema picks a subschema's validator by its own `$schema`, so a union under one
    naming 2020-12 ran on JSON Schema's own validator, unbudgeted (2 steps counted), its `anyOf` building 60,001
    errors over this input. The check's own dialect is removed wherever a schema stands: the union is still tried a
    branch at a time up to a first error, each step counted."""
    found = shape(schema({"tags": tags}, **{"$schema": DIALECT}), takes_csv=False)
    assert found.check({"tags": ["abcdefghijklmnopq"] * 20_000}) == Checked(
        ["`tags` fits none of the shapes this input allows."]
    )
    assert 5 < schedule_checks.MAX_STEPS - found.budget.left < 50 and found.partial == frozenset()


def test_a_dialect_declared_inside_still_spends_the_budget(monkeypatch) -> None:
    """The review of revision 4: a valid 20,000-item list beneath a nested `$schema` finished on 4 steps. It spends
    the check's steps as anywhere else, through a reference too, and runs out."""
    monkeypatch.setattr(schedule_checks, "MAX_STEPS", 4)
    nested = {"type": "object", "properties": {"tags": {"$ref": "#/$defs/tags"}},
              "$defs": {"tags": {"$schema": DIALECT, "type": "array", "items": {"type": "string"}}}}  # fmt: skip
    with pytest.raises(Exhausted):
        shape(nested, takes_csv=False).check({"tags": ["a"] * 20_000})


def test_another_dialect_isnt_checked_and_says_so() -> None:
    """A schema naming another dialect is read by that dialect's rules, which the check doesn't keep: it isn't checked
    (never a reason, no step spent), and `$schema` is named, for validate to say the check was partial."""
    found = shape(schema({"site": {"$schema": "http://json-schema.org/draft-07/schema#", "type": "integer"}}),
                  takes_csv=False)  # fmt: skip
    assert found.check(STORED) == Checked([]) and found.partial == frozenset({"$schema"})
    assert found.budget.left == schedule_checks.MAX_STEPS


def test_a_reference_resolves_wherever_its_schema_stands() -> None:
    """The draft's schema is kept as written but for the check's own `$schema`: a reference resolves as it does for the
    draft, its definition's structure checked, and a keyword the check doesn't evaluate there (a `not`) named."""
    kept = {"properties": {"inner": {"type": "string"}}, "not": {"type": "integer"}}
    referring = {"type": "object", "properties": {"site": {"$ref": "#/$defs/kept"}}, "$defs": {"kept": kept}}
    found = shape(referring, takes_csv=False)
    assert found.check({"site": {"inner": 1}}) == Checked(["`site.inner` must be text now."])
    assert found.partial == frozenset({"not"})


def test_a_key_its_pattern_allows_is_no_extra_field() -> None:
    """Keywords the check doesn't evaluate stay in the schema: `additionalProperties` still reads `patternProperties`,
    so a key a pattern allows is never reported as one the input no longer allows."""
    patterned = schema({}, patternProperties={"^t": {}}, additionalProperties=False)
    assert shape(patterned, takes_csv=False).check({"token": "x"}) == Checked([])


class Endless:
    """A validator whose errors never end, all at one place: only the error budget can stop the check."""

    def __init__(self) -> None:
        self.read = 0

    def iter_errors(self, value: Any) -> Iterator[ValidationError]:
        for n in itertools.count():
            self.read = n + 1
            yield ValidationError("x", validator="type", validator_value="integer", instance="a", path=[n])


def test_the_errors_read_are_bounded_whatever_the_validator_yields() -> None:
    endless = Endless()
    budget = schedule_checks.Budget(schedule_checks.MAX_STEPS)
    checked = Shape(False, {"type": "object"}, frozenset(), endless, budget).check({})  # type: ignore[arg-type]
    assert checked == Checked(["`*` must be a whole number now."], more=True)
    assert endless.read == schedule_checks.MAX_ERRORS + 1


def test_a_reason_is_bounded_in_length() -> None:
    """A field's name is the draft's own, and may be long: a reason keeps `MAX_REASON_CHARS` of it at most."""
    long = "f" * 2_000
    (reason,) = shape(schema({}, required=[long]), takes_csv=False).check({}).reasons
    assert len(reason) == schedule_checks.MAX_REASON_CHARS and reason.endswith("…")
```

Create `backend/tests/apps/api/test_schedule_checks_api.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A draft that would break the workflow's live schedules is said so, by validate and by publish (4c-3a ruling 7):
nobody can see a schedule's stored input, so the server checks it against the draft's input, by its shape alone, and
says which schedules and why, never what their input holds. A warning: publishing goes ahead."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from dewpoint.apps import schedule_checks
from tests.apps.api.test_run_requests_api import as_role
from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, TOKEN_GRAPH, published
from tests.support.keys import FixtureKeys

pytestmark = pytest.mark.usefixtures("development_deployment")
BODY = {"cron": "0 9 * * 1-5", "time_zone": "Europe/Paris", "input": {"token": TOKEN, "site": "a"}}
BREAKING = SCHEMA | {
    "properties": {"token": {"type": "string", "x-sensitive": True, "maxLength": 3},
                   "site": {"type": "integer"}, "floor": {"type": "integer"}},
    "required": ["token", "floor"],
}  # fmt: skip


@pytest.fixture
def keyed_app(app: Any) -> Any:
    app.state.keys = KEYS
    return app


@pytest.fixture
async def workflow(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
    return await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)


def url(ctx: Any, path: str) -> str:
    return f"/api/v1/t/{ctx.tenant_id}{path}"


async def drafted(editor: Any, ctx: Any, wf: uuid.UUID, settings: dict[str, Any]) -> None:
    revision = (await editor.get(url(ctx, f"/workflows/{wf}"))).json()["draft_revision"]
    saved = await editor.put(url(ctx, f"/workflows/{wf}/draft"), json=TOKEN_GRAPH | {"settings": settings},
                             headers={"If-Match": str(revision)})  # fmt: skip
    assert saved.status_code == 200, saved.text


async def scheduled(editor: Any, ctx: Any, wf: uuid.UUID, body: dict[str, Any] = BODY) -> str:
    made = await editor.post(url(ctx, f"/workflows/{wf}/schedules"), json=body)
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


async def test_validate_says_which_live_schedules_a_draft_would_break_and_why(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """Stored inputs `{"token": …, "site": …}` against a draft that requires `floor` and makes `site` a whole number:
    those two reasons for each, in the draft's own words, the oldest schedule first. `token`'s new `maxLength` is a
    value's content: never checked, never named. A draft both fit lists none; a deleted schedule is never read."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    first = await scheduled(editor, ctx, wf)
    second = await scheduled(editor, ctx, wf, BODY | {"input": {"token": TOKEN, "site": "b"}})
    gone = await scheduled(editor, ctx, wf)
    assert (await editor.delete(url(ctx, f"/schedules/{gone}"))).status_code == 204
    await drafted(editor, ctx, wf, {"input_schema": BREAKING | {"required": ["token"]} | {
        "properties": BREAKING["properties"] | {"site": {"type": "string"}}}})  # fmt: skip
    clean = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert clean["schedule_breaks"] == [] and not [d for d in clean["diagnostics"] if d["code"].startswith("schedule")]
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    answer = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    why = ["`floor` is required now.", "`site` must be a whole number now."]
    assert body["schedule_breaks"] == [
        {"schedule_id": first, "reasons": why, "more": False},
        {"schedule_id": second, "reasons": why, "more": False},
    ]
    warned = [d for d in body["diagnostics"] if d["code"] == "schedule.input_refused"]
    assert warned == [{"code": "schedule.input_refused", "node": None, "field": "/settings/input_schema", "fix": None,
                       "severity": "warning", "message": schedule_checks.REFUSED.format(n=2, s="s")}]  # fmt: skip
    assert body["valid"] is True and TOKEN not in answer.text


async def test_a_draft_that_takes_a_csv_file_breaks_every_schedule(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    sid = await scheduled(editor, ctx, wf)
    csv = {"columns": [{"header": "Site", "name": "site", "type": "string"}]}
    await drafted(editor, ctx, wf, {"input_schema": SCHEMA, "csv": csv})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == [{"schedule_id": sid, "reasons": [schedule_checks.CSV], "more": False}]
    assert [d["field"] for d in body["diagnostics"] if d["code"] == "schedule.input_refused"] == ["/settings/csv"]


async def test_publish_warns_and_publishes(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
    """A warning, never a refusal: the version is published, its answer warns, and the schedule fails at its next
    firing until its input is replaced (the owner chose warn, not refuse)."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    revision = (await editor.get(url(ctx, f"/workflows/{wf}"))).json()["draft_revision"]
    answer = await editor.post(url(ctx, f"/workflows/{wf}/publish"), headers={"If-Match": str(revision)})
    assert answer.status_code == 201, answer.text
    assert [d["message"] for d in answer.json()["warnings"] if d["code"] == "schedule.input_refused"] == [
        schedule_checks.REFUSED.format(n=1, s="")
    ]


async def test_a_schedule_whose_input_cant_be_read_is_counted_unchecked(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """The tenant's key unreadable: validate still answers, the schedules counted unchecked, never refused."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    keyed_app.state.keys = FixtureKeys(missing={str(ctx.tenant_id)})
    answer = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    assert answer.status_code == 200, answer.text
    assert answer.json()["schedule_breaks"] == []
    assert [d["message"] for d in answer.json()["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=1, s="")
    ]


async def test_the_check_reads_a_bounded_number_of_schedules(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """At most `MAX_CHECKED`, the oldest first; the rest are counted unchecked."""
    monkeypatch.setattr(schedule_checks, "MAX_CHECKED", 2)
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    first = [await scheduled(editor, ctx, wf) for _ in range(3)]
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert [b["schedule_id"] for b in body["schedule_breaks"]] == first[:2]
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=1, s="")
    ]


async def test_a_draft_whose_input_schema_is_wrong_isnt_checked(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """An input schema with an error (here, a type that isn't one) can't be checked against: validate says its error,
    and nothing about the schedules, never a failure of its own."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": {"type": "object", "properties": {"site": {"type": 5}}}})
    answer = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["valid"] is False and body["schedule_breaks"] == []
    assert not [d for d in body["diagnostics"] if d["code"].startswith("schedule.")]


async def test_publishing_a_csv_draft_warns_at_its_declaration(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    csv = {"columns": [{"header": "Site", "name": "site", "type": "string"}]}
    await drafted(editor, ctx, wf, {"input_schema": SCHEMA, "csv": csv})
    revision = (await editor.get(url(ctx, f"/workflows/{wf}"))).json()["draft_revision"]
    answer = await editor.post(url(ctx, f"/workflows/{wf}/publish"), headers={"If-Match": str(revision)})
    assert answer.status_code == 201, answer.text
    assert [d["field"] for d in answer.json()["warnings"] if d["code"] == "schedule.input_refused"] == ["/settings/csv"]


async def test_validate_reads_nested_fields_references_and_all_of(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """The review of revision 1: a requirement under a reference, or in an `allOf`, breaks every firing as surely as
    one at the root, and validate says so, in the draft's words."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    sid = await scheduled(editor, ctx, wf)
    drafted_schema = {
        "type": "object",
        "properties": {"token": {"type": "string", "x-sensitive": True}, "site": {"$ref": "#/$defs/site"}},
        "$defs": {"site": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
        "allOf": [{"required": ["area"]}],
    }
    await drafted(editor, ctx, wf, {"input_schema": drafted_schema})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == [{"schedule_id": sid, "reasons": [
        "`area` is required now.", "`site` must be an object now."], "more": False}]  # fmt: skip
    assert TOKEN not in str(body)


async def test_an_integral_number_fits_a_whole_number(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """The review of revision 1: `2.0` is an integer to JSON Schema and to admission, which stored it; an unchanged
    input never warns about it."""
    floors = SCHEMA | {"properties": SCHEMA["properties"] | {"floor": {"type": "integer"}}}
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings,
                              TOKEN_GRAPH | {"settings": {"input_schema": floors}})  # fmt: skip
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf, BODY | {"input": {"token": TOKEN, "floor": 2.0}})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == [] and not [d for d in body["diagnostics"] if d["code"].startswith("schedule.")]


async def test_structure_the_check_cant_read_is_said(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
    """A draft whose input uses structure a shape can't keep (here `not`, and `oneOf`'s one-only rule): the live
    schedules were checked in part, and validate names what wasn't read. No schedule, no warning."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    partly = SCHEMA | {
        "not": {"required": ["site", "area"]},
        "properties": SCHEMA["properties"] | {"site": {"oneOf": [{"type": "string"}, {"const": 1}]}},
    }
    await drafted(editor, ctx, wf, {"input_schema": partly})
    quiet = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert not [d for d in quiet["diagnostics"] if d["code"].startswith("schedule.")]
    await scheduled(editor, ctx, wf)
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == []
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.partly_checked"] == [
        schedule_checks.PARTLY.format(keywords="`not`, `oneOf`")
    ]


async def test_the_schedules_and_their_number_come_from_one_statement(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """The review of revision 1: read apart, a schedule deleted between the rows and their count made the unchecked
    number negative. One statement reads both, in one snapshot."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    seen: list[str] = []

    def on(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        if "FROM schedules" in statement:
            seen.append(statement)

    event.listen(Engine, "before_cursor_execute", on)
    try:
        assert (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).status_code == 200
    finally:
        event.remove(Engine, "before_cursor_execute", on)
    assert len(seen) == 1 and "count(*) OVER ()" in seen[0]


async def test_one_large_input_gives_a_bounded_answer(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """The review of revision 2: a 400 KB stored input (under the 1 MiB request limit) whose 20,000 items all break
    the draft's new item type gave 20,000 reasons, a 909 KB answer for one schedule. Now it gives `MAX_REASONS` and
    says there were more."""
    tagged = SCHEMA | {"properties": SCHEMA["properties"] | {"tags": {"type": "array", "items": {"type": "string"}}}}
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings,
                              TOKEN_GRAPH | {"settings": {"input_schema": tagged}})  # fmt: skip
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    sid = await scheduled(editor, ctx, wf, BODY | {"input": {"token": TOKEN, "tags": ["abcdefghijklmnopq"] * 20_000}})
    integers = tagged | {"properties": tagged["properties"] | {"tags": {"type": "array", "items": {"type": "integer"}}}}
    await drafted(editor, ctx, wf, {"input_schema": integers})
    answer = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    (found,) = answer.json()["schedule_breaks"]
    assert (found["schedule_id"], len(found["reasons"]), found["more"]) == (sid, schedule_checks.MAX_REASONS, True)
    assert len(answer.content) < 20_000


async def test_the_stored_input_one_check_reads_is_bounded_in_bytes(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """Counted in sealed bytes, never time: past `MAX_INPUT_BYTES`, the oldest first, the rest are counted unchecked."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    first = await scheduled(editor, ctx, wf)
    await scheduled(editor, ctx, wf)
    async with owner_sessionmaker() as s:
        size = (await s.execute(text("select length(input) from schedules where id = :i"), {"i": first})).scalar_one()
    monkeypatch.setattr(schedule_checks, "MAX_INPUT_BYTES", size + 1)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert [b["schedule_id"] for b in body["schedule_breaks"]] == [first]
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=1, s="")
    ]


async def test_the_check_runs_off_the_event_loop(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """Decoding and checking the stored inputs is CPU work: it runs in a worker thread, never on the event loop."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    threaded: list[str] = []
    real = asyncio.to_thread

    async def recorded(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        threaded.append(getattr(fn, "__name__", ""))
        return await real(fn, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recorded)
    assert (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()["schedule_breaks"]
    assert "checked_all" in threaded


async def test_past_the_byte_budget_no_stored_input_is_fetched(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """The review of revision 3: the 2 MiB budget was applied after every row's input had been fetched. One statement
    now picks, the oldest first, the schedules whose sealed inputs fit it (by their stored length) and fetches only
    theirs; the others come back as ids, with the live total, in the same snapshot."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    first = await scheduled(editor, ctx, wf)
    second = await scheduled(editor, ctx, wf)
    async with owner_sessionmaker() as s:
        size = (await s.execute(text("select length(input) from schedules where id = :i"), {"i": first})).scalar_one()
        monkeypatch.setattr(schedule_checks, "MAX_INPUT_BYTES", size + 1)
        read = await schedule_checks.read_schedules(s, uuid.UUID(str(wf)))
    assert read.live == 2
    assert [(str(i), sealed is not None) for i, sealed in read.rows] == [(first, True), (second, False)]


async def test_a_check_that_runs_out_of_steps_counts_the_rest_unchecked(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """The step budget, through validate: a check that runs out says how many schedules it didn't check."""
    monkeypatch.setattr(schedule_checks, "MAX_STEPS", 3)
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == []
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=2, s="s")
    ]


async def test_a_dialect_declared_inside_is_budgeted_through_validate(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """The review of revision 4, through validate: a fitting input beneath a nested `$schema` spends the check's
    steps; when they run out, the schedule is counted unchecked, never silently passed."""
    monkeypatch.setattr(schedule_checks, "MAX_STEPS", 4)
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    dialect = "https://json-schema.org/draft/2020-12/schema"
    nested = SCHEMA | {"properties": {"token": {"$schema": dialect, "type": "string", "x-sensitive": True},
                                      "site": {"$schema": dialect, "type": "string"}}}  # fmt: skip
    await drafted(editor, ctx, wf, {"input_schema": nested})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == []
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=1, s="")
    ]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --frozen pytest -q tests/apps/test_schedule_checks.py tests/apps/api/test_schedule_checks_api.py`
Expected: 2 errors at collection: `No module named 'dewpoint.apps.schedule_checks'`.

- [ ] **Step 3: The check, and validate's and publish's warnings**

Create `backend/src/dewpoint/apps/schedule_checks.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Whether a draft would break the workflow's live schedules (4c-3a ruling 7). Each schedule holds a sealed input,
checked against the active version when it's written and again at each firing; publishing an input the stored one
doesn't fit makes the schedule fail at every firing, and nobody can see the stored input to know. So validate and
publish check it, and say which schedules and why, never what their input holds: a warning, never a refusal.

The check is of the stored input's shape alone. JSON Schema's own validator checks it against the draft's input as
written, extended so that it evaluates only structure (`type`, `properties`, `required`, `additionalProperties`,
`items`, `prefixItems`, references, `allOf`, `anyOf`, `dependentRequired`, `dependentSchemas`), with its own types
(`2.0` is an integer); every other keyword holds for every value. `oneOf` is evaluated as `anyOf`; the structure a
shape can't keep (`not`, `if`, `propertyNames`, …) holds, and is named, for validate to say the check was partial. So
the check accepts every value the draft does: a value it refuses, the draft refuses too. The document is kept as
written, so references resolve as they do for the draft, but for `$schema`: the check's own dialect is removed where
a schema names it, since jsonschema validates a schema it descends into with the validator its `$schema` names; another
dialect isn't checked, and is named. Never a value's content: a draft's `maximum`, `maxLength` or `const` checked
against a stored value would let whoever can validate a draft learn a sensitive value a bit at a time. A reason names
the draft's own places and fields, never the stored input's. A draft that takes a CSV file fits no schedule: its rows
come from an upload only (engine 2b spec §8.1).

Its work is bounded in units, never time:
- a check fetches the oldest schedules whose sealed inputs fit 2 MiB together, 100 at most, picked by their stored
  length in the same statement that counts them, so no other input is fetched;
- every keyword it evaluates, at any depth, spends one of the check's 50,000 steps, and its `anyOf` tries a branch only
  up to its first error, keeping none (JSON Schema's own builds every error of every failing branch first);
- from one stored input it reads 100 errors, lazily, and keeps 5 distinct reasons, each of 300 characters at most.
What a bound leaves out is said: a schedule as unchecked, a reason list as having more. Decoding and checking run in a
worker thread."""

import asyncio
import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from dewpoint.apps.schedules import INPUT_PURPOSE
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource, key_unreadable
from dewpoint.core.models.schedules import Schedule
from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.runtime.projection import location
from dewpoint.engine.schema_refs import SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE

log = structlog.get_logger("dewpoint.schedule_checks")
MAX_CHECKED = 100  # live schedules one check reads, the oldest first; the rest are counted unchecked
MAX_INPUT_BYTES = 2 * 1024 * 1024  # their sealed input one check reads, the oldest first; past it, counted unchecked
MAX_STEPS = 50_000  # keywords one check evaluates, at any depth, for all its inputs together
MAX_ERRORS = 100  # errors read from one stored input, lazily
MAX_REASONS = 5  # distinct reasons kept for one, in the order found
MAX_REASON_CHARS = 300  # a reason's length at most: a name the draft gives may be long
CSV = "This input takes a CSV file now: a schedule can't give its rows."
REFUSED = (
    "Publishing this would make {n} live schedule{s} fail at every firing: their stored input doesn't fit this input. "
    "Once it's published, replace it, or keep the input as it was."
)
PARTLY = (
    "The live schedules were checked against this input in part: its {keywords} can't be checked by shape, so a "
    "schedule it would refuse may not be listed."
)
UNCHECKED = (
    "Not checked against this input: {n} live schedule{s}, either past what one check reads (the oldest 100, 2 MiB of "
    "stored input, 50,000 checking steps) or with a stored input that couldn't be read."
)
_TYPES = {"string": "text", "integer": "a whole number", "number": "a number", "boolean": "yes or no",
          "array": "a list", "object": "an object", "null": "null"}  # fmt: skip
# The keywords the check evaluates (4c-3a ruling 7): structure. Every other keyword is evaluated as nothing: one that
# tests a value's content (`const`, `maximum`, `maxLength`, `format`, …) or annotates, and the structure a shape can't
# keep without refusing what the draft accepts (`PARTIAL`, named). `oneOf` is evaluated as `anyOf`, which only widens.
_STRUCTURE = frozenset({"type", "properties", "required", "additionalProperties", "items", "prefixItems", "$ref",
                        "allOf", "anyOf", "dependentRequired", "dependentSchemas"})  # fmt: skip
PARTIAL = frozenset({"oneOf", "not", "if", "then", "else", "propertyNames", "patternProperties",
                     "unevaluatedProperties", "unevaluatedItems", "contains"})  # fmt: skip
# The check's own dialect: `$schema` naming it is removed wherever a schema stands, since jsonschema picks the
# validator of a schema it descends into by that schema's `$schema`, and the registered one has no budget.
DIALECT = frozenset({"https://json-schema.org/draft/2020-12/schema", "https://json-schema.org/draft/2020-12/schema#"})


def _read(schema: Any) -> tuple[Any, frozenset[str]]:
    """`schema` as the check reads it, and what it can't keep. The document stays as written, so every reference
    resolves as it does for the draft, but for one keyword: `$schema` naming the check's own dialect is removed
    wherever a schema stands (`schema_refs`' schema positions), so descending never leaves the check's validator.
    Another dialect is read by its own rules: a draft naming one isn't checked (`$schema`, named)."""
    found: set[str] = set()

    def walk(node: Any) -> Any:
        if not isinstance(node, Mapping):
            return node  # a boolean schema
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "$schema" and isinstance(value, str):
                if value not in DIALECT:
                    found.add(key)
                continue
            if key in PARTIAL:
                found.add(key)
            if key in SCHEMA_ONE:
                out[key] = walk(value)
            elif key in SCHEMA_LIST and isinstance(value, list):
                out[key] = [walk(sub) for sub in value]
            elif key in SCHEMA_MAP and isinstance(value, Mapping):
                out[key] = {name: walk(sub) for name, sub in value.items()}
            else:
                out[key] = value
        return out

    return walk(schema), frozenset(found)


def _reasons(e: ValidationError, schema: Mapping[str, Any]) -> Iterator[str]:
    """Why a value doesn't have the shape, in the draft's own words: a place as far as the draft declares it (a key
    the data supplied shows as `*`), a name the draft gives; never a value, never a stored name."""
    where = location(list(e.absolute_path), schema)
    named = "" if where == "(root)" else f"{where}."
    present = e.instance if isinstance(e.instance, dict) else {}
    rule: Any = e.validator_value  # the draft's own: a list of names, a map of them, a type
    match e.validator:
        case "required":
            yield from (f"`{named}{n}` is required now." for n in (rule if isinstance(rule, list) else [])
                        if isinstance(n, str) and n not in present)  # fmt: skip
        case "dependentRequired":
            pairs = rule.items() if isinstance(rule, Mapping) else []
            yield from (f"`{named}{d}` is required now, beside `{named}{k}`." for k, deps in pairs if k in present
                        for d in deps if isinstance(d, str) and d not in present)  # fmt: skip
        case "type":
            kinds = [rule] if isinstance(rule, str) else list(rule) if isinstance(rule, list) else []
            yield f"`{where}` must be {' or '.join(_TYPES.get(k, str(k)) for k in kinds)} now."
        case "additionalProperties":
            yield f"{'It' if not named else f'`{where}`'} has a field this input no longer allows."
        case "anyOf":
            yield f"{'It' if not named else f'`{where}`'} fits none of the shapes this input allows."
        case _:
            yield f"{'It' if not named else f'`{where}`'} doesn't have the shape this input declares."


class Exhausted(Exception):
    """The check's steps ran out: what's left isn't checked."""


class Budget:
    """The steps a check has left, for all its inputs: each keyword it evaluates spends one."""

    def __init__(self, steps: int) -> None:
        self.left = steps

    def spend(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise Exhausted


def _any_of(validator: Any, branches: list[Any], instance: Any, schema: Any) -> Iterator[ValidationError]:
    """`anyOf`, tried a branch at a time up to its first error, none kept: the check never names them. A branch that
    has none ends it."""
    for index, branch in enumerate(branches):
        if next(validator.descend(instance, branch, schema_path=index), None) is None:
            return
    yield ValidationError("no branch fits")


def _ignored(validator: Any, value: Any, instance: Any, schema: Any) -> None:
    """A keyword the check doesn't evaluate: it holds for every value."""


def _counting(schema: Mapping[str, Any], budget: Budget) -> Any:
    """JSON Schema's own validator for `schema`, extended: each keyword spends a step of `budget` before it's
    evaluated; only structure is evaluated, every other keyword holding; `anyOf` (and `oneOf`) tried lazily."""

    def counted(keyword: Any) -> Any:
        def evaluated(validator: Any, value: Any, instance: Any, at: Any) -> Any:
            budget.spend()
            return keyword(validator, value, instance, at)

        return evaluated

    keywords = {
        name: counted(fn if name in _STRUCTURE else _ignored) for name, fn in Draft202012Validator.VALIDATORS.items()
    }
    keywords |= {"anyOf": counted(_any_of), "oneOf": counted(_any_of)}
    extended = validators.extend(Draft202012Validator, keywords)  # type: ignore[no-untyped-call]  # unannotated in 4.26
    return extended(schema)


def _short(reason: str) -> str:
    return reason if len(reason) <= MAX_REASON_CHARS else reason[: MAX_REASON_CHARS - 1] + "…"


@dataclass(frozen=True)
class Checked:
    """Why one stored input wouldn't fit, in order; `more` when the check stopped at a budget with more to say."""

    reasons: list[str]
    more: bool = False


@dataclass(frozen=True)
class Shape:
    """A draft's input as the check reads it, to check stored inputs' shape against (4c-3a ruling 7)."""

    takes_csv: bool
    schema: Mapping[str, Any]
    partial: frozenset[str]  # the structure it couldn't keep: what the check didn't read
    validator: Any  # built once, for every stored input it checks, spending from `budget`; None: not checked
    budget: Budget

    def check(self, value: Any) -> Checked:
        """Why `value` wouldn't fit, each told once, in order; no reason when its shape fits. Its errors are read
        lazily, `MAX_ERRORS` at most, and `MAX_REASONS` distinct reasons kept: past either, `more`. Raises Exhausted
        when the check's steps run out."""
        if self.takes_csv:
            return Checked([CSV])
        if self.validator is None:  # another dialect's: not checked, and named in `partial`
            return Checked([])
        kept: list[str] = []
        for read, e in enumerate(self.validator.iter_errors(value)):
            if read == MAX_ERRORS:
                return Checked(sorted(kept), more=True)
            for reason in map(_short, _reasons(e, self.schema)):
                if reason in kept:
                    continue
                if len(kept) == MAX_REASONS:
                    return Checked(sorted(kept), more=True)
                kept.append(reason)
        return Checked(sorted(kept))


def shape(input_schema: Mapping[str, Any], *, takes_csv: bool) -> Shape:
    """`input_schema` as the check reads it: its shape, with JSON Schema's own type checker (`2.0` is an integer)."""
    read, partial = _read(input_schema)
    schema = read if isinstance(read, Mapping) else {}
    budget = Budget(MAX_STEPS)
    return Shape(takes_csv, schema, partial, None if "$schema" in partial else _counting(schema, budget), budget)


def checked_all(
    input_schema: Mapping[str, Any], takes_csv: bool, opened: list[tuple[uuid.UUID, bytes]]
) -> tuple[frozenset[str], list[tuple[uuid.UUID, Checked]], int]:
    """The stored inputs `opened` checked against `input_schema`'s shape, the oldest first: CPU work, run in a worker
    thread. The structure the shape couldn't keep, each input that wouldn't fit, and how many weren't checked: the one
    the steps ran out in, and the rest."""
    drafted = shape(input_schema, takes_csv=takes_csv)
    refused: list[tuple[uuid.UUID, Checked]] = []
    for n, (schedule_id, plaintext) in enumerate(opened):
        try:
            checked = drafted.check(json.loads(plaintext))
        except Exhausted:
            return drafted.partial, refused, len(opened) - n
        if checked.reasons:
            refused.append((schedule_id, checked))
    return drafted.partial, refused, 0


@dataclass(frozen=True)
class Read:
    rows: list[tuple[uuid.UUID, bytes | None]]  # the oldest live schedules, 100 at most; an input past the bytes, None
    live: int  # every live schedule of the workflow


async def read_schedules(s: AsyncSession, workflow_id: uuid.UUID) -> Read:
    """The oldest `MAX_CHECKED` live schedules (a deleted one's tombstone left out), each with its sealed input when
    the oldest ones' inputs fit `MAX_INPUT_BYTES` together, and how many are live, in one statement and one snapshot.
    The inputs are picked by their stored length (`octet_length`, which reads no payload), so no other is fetched."""
    order = (Schedule.created_at, Schedule.id)
    sized = (
        select(Schedule.id.label("id"), func.count().over().label("live"),
               func.row_number().over(order_by=order).label("n"),
               func.sum(func.octet_length(Schedule.input)).over(order_by=order).label("running"))
        .where(Schedule.workflow_id == workflow_id, Schedule.deleted_at.is_(None))
        .subquery()
    )  # fmt: skip
    kept = aliased(Schedule)
    found = (await s.execute(
        select(sized.c.id, kept.input, sized.c.live)
        .select_from(sized)
        .outerjoin(kept, and_(kept.id == sized.c.id, sized.c.running <= MAX_INPUT_BYTES))
        .where(sized.c.n <= MAX_CHECKED)
        .order_by(sized.c.n)
    )).all()  # fmt: skip
    return Read([(r.id, r.input) for r in found], found[0].live if found else 0)


@dataclass(frozen=True)
class Breaks:
    refused: list[tuple[uuid.UUID, Checked]]  # each live schedule whose stored input wouldn't fit, with why
    unchecked: int  # live schedules past `MAX_CHECKED`, or whose stored input couldn't be read
    partial: frozenset[str] = frozenset()  # the draft's structure the check didn't read, when it read a schedule


async def breaks(
    s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, workflow_id: uuid.UUID, *,
    input_schema: Mapping[str, Any], takes_csv: bool,
) -> Breaks:  # fmt: skip
    """The workflow's live schedules (a deleted one's tombstone left out) whose stored input `input_schema` wouldn't
    fit, by its shape (`read_schedules` says which are read). One past what a check reads, or whose key can't be
    read, is counted unchecked; anything else raises. The checking runs in a worker thread."""
    read = await read_schedules(s, workflow_id)
    unchecked = read.live - sum(1 for _, sealed in read.rows if sealed is not None)
    cipher = ClaimCipher(keys, purpose=INPUT_PURPOSE)
    opened: list[tuple[uuid.UUID, bytes]] = []
    for schedule_id, sealed in read.rows:
        if sealed is None:  # past the bytes a check reads: counted above, never fetched
            continue
        try:
            opened.append((schedule_id, await cipher.open(str(tenant_id), str(schedule_id), sealed)))
        except Exception as e:
            if not key_unreadable(e):
                raise
            log.warning("schedule_input_unread", error=type(e).__name__)
            unchecked += 1
    partial, refused, exhausted = await asyncio.to_thread(checked_all, input_schema, takes_csv, opened)
    return Breaks(refused, unchecked + exhausted, partial if opened and not takes_csv else frozenset())


def warnings(found: Breaks, *, takes_csv: bool) -> list[Diagnostic]:
    """What validate and publish warn of: the schedules that would break, at the input (or the CSV declaration), and
    the ones not checked."""
    out: list[Diagnostic] = []
    if found.refused:
        n = len(found.refused)
        out.append(Diagnostic(code="schedule.input_refused", message=REFUSED.format(n=n, s="s" if n > 1 else ""),
                              field="/settings/csv" if takes_csv else "/settings/input_schema",
                              severity="warning"))  # fmt: skip
    if found.unchecked:
        n = found.unchecked
        out.append(Diagnostic(code="schedule.unchecked", message=UNCHECKED.format(n=n, s="s" if n > 1 else ""),
                              severity="warning"))  # fmt: skip
    if found.partial:
        named = ", ".join(f"`{k}`" for k in sorted(found.partial))
        out.append(Diagnostic(code="schedule.partly_checked", message=PARTLY.format(keywords=named),
                              field="/settings/input_schema", severity="warning"))  # fmt: skip
    return out


def checkable(diagnostics: Sequence[Diagnostic]) -> bool:
    """Whether a draft's input can be checked against: not when its input schema or CSV declaration has an error."""
    return not any(d.severity == "error" and (d.field or "").startswith(("/settings/input_schema", "/settings/csv"))
                   for d in diagnostics)  # fmt: skip
```

In `backend/src/dewpoint/apps/api/routes/workflows.py`, import `dataclasses` (with `re` and `uuid`),
`schedule_checks` (`from dewpoint.apps import schedule_checks, workflow_ops, workflow_summary`), `get_keys` (`from
dewpoint.apps.api.routes.run_requests import get_keys`) and `KeySource` (`from dewpoint.core.crypto.keys import
KeySource`). `validate_draft` takes the keys, after `settings`:

```python
    keys: KeySource = Depends(get_keys),
```

and between `expressions = …` and its `return`, checks the live schedules:

```python
    # The live schedules this draft would break, published (4c-3a ruling 7): a warning, by the stored input's shape.
    found = schedule_checks.Breaks([], 0)
    if checked.graph is not None and schedule_checks.checkable(checked.diagnostics):
        takes_csv = checked.graph.settings.csv is not None
        found = await schedule_checks.breaks(db, keys, ctx.tenant_id, wf.id, takes_csv=takes_csv,
                                             input_schema=checked.graph.settings.input_schema)  # fmt: skip
        checked = dataclasses.replace(
            checked, diagnostics=[*checked.diagnostics, *schedule_checks.warnings(found, takes_csv=takes_csv)]
        )
```

Its answer gains, after `"diagnostics"`:

```python
        "schedule_breaks": [
            {"schedule_id": str(sid), "reasons": why.reasons, "more": why.more} for sid, why in found.refused
        ],
```

`publish` takes the keys too (after `settings`), and its successful answer becomes:

```python
    takes_csv = workflow_ops.declares_csv(out.version.graph)
    found = await schedule_checks.breaks(db, keys, ctx.tenant_id, wf.id, input_schema=out.version.input_schema or {},
                                         takes_csv=takes_csv)  # fmt: skip
    return {
        "version_id": str(out.version.id),
        "number": out.version.number,
        "warnings": [d.to_json() for d in [*out.warnings, *schedule_checks.warnings(found, takes_csv=takes_csv)]],
    }
```

In `backend/src/dewpoint/apps/api/responses.py`, before `ValidationOut`, add:

```python
class ScheduleBreakOut(_Answer):
    """A live schedule the draft, published, would make fail at every firing (4c-3a ruling 7): why, by its stored
    input's shape, in the draft's own words; never what the input holds."""

    schedule_id: str
    reasons: list[str]  # at most 5, each of 300 characters at most
    more: bool  # the check stopped at its budget with more to say about this one
```

and `ValidationOut` gains, after `conditional_steps`:

```python
    schedule_breaks: list[ScheduleBreakOut]  # the live schedules it would break, published, the oldest first
```

- [ ] **Step 4: Run them to see them pass**

Run: `uv run --frozen pytest -q -n auto tests/apps/test_schedule_checks.py tests/apps/api/test_schedule_checks_api.py tests/apps/api/test_workflows.py tests/apps/api/test_workflow_versions.py tests/apps/api/test_workflow_portable.py tests/apps/api/test_commit_before_response.py`
Expected: every test passes.

- [ ] **Step 5: Lint, types, import contracts, commit**

Run: `uv run --frozen ruff format src tests && uv run --frozen ruff check src tests && uv run --frozen mypy src &&
uv run --frozen lint-imports`
Expected: clean; 11 contracts kept.

```bash
git add backend/src/dewpoint/apps/schedule_checks.py backend/src/dewpoint/apps/api/routes/workflows.py \
  backend/src/dewpoint/apps/api/responses.py backend/tests/apps/test_schedule_checks.py \
  backend/tests/apps/api/test_schedule_checks_api.py
git commit -m "feat(workflows): validate and publish say which live schedules a draft would break

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4c-3a, milestone 2 (date)` to the ledger (the tasks' commits, each run's result, any mid-slice ruling),
commit it, and **pause** for the owner's review: Task 7 decides what validate may reveal of a schedule's sealed input.
Milestone 3 starts on the owner's word.

---

# Milestone 3 — the client's contract

### Task 8: Named answers for the trigger routes and the start form

**Files:**
- Modify: `backend/src/dewpoint/apps/api/responses.py` (the new models, at the end)
- Modify: `backend/src/dewpoint/apps/api/routes/schedules.py`, `routes/webhooks.py`, `routes/run_requests.py`
  (`response_model` on each route the editor calls)
- Modify: `backend/tests/apps/api/test_openapi.py`, `backend/tests/apps/api/test_webhooks_api.py`

**Interfaces:**
- Consumes: the answers as Tasks 3–5 and 7 left them (`schedules.body`, `webhooks.endpoint_body`, `binding_body`,
  `endpoint_summary`, `forms.form_fields`, `forms.csv_form`).
- Produces: the models `UncountedOut`, `ScheduleOut`, `SchedulesOut`, `EndpointOut`, `EndpointCreatedOut`,
  `EndpointsOut`, `SecretOut`, `FilterClauseOut`, `WebhookBindingOut`, `WebhookBindingsOut`, `BindingEndpointOut`,
  `WorkflowBindingOut`, `WorkflowBindingsOut`, `StartFieldOut`, `CsvColumnFormOut`, `CsvFormOut`, `StartFormOut`; the
  schema's names for the 14 routes below.

- [ ] **Step 1: Write the failing tests**

At the end of `backend/tests/apps/api/test_openapi.py`, add:

```python
# What the web client calls in slice 4c-3, trigger setup (4c-3a ruling 5): each answers a named model.
SLICE_4C3 = [
    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/schedules"),
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/schedules"),
    ("get", "/api/v1/t/{tenant_id}/schedules/{schedule_id}"),
    ("patch", "/api/v1/t/{tenant_id}/schedules/{schedule_id}"),
    ("post", "/api/v1/t/{tenant_id}/webhook-endpoints"),
    ("get", "/api/v1/t/{tenant_id}/webhook-endpoints"),
    ("get", "/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}"),
    ("patch", "/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}"),
    ("post", "/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}/secret"),
    ("post", "/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings"),
    ("get", "/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings"),
    ("patch", "/api/v1/t/{tenant_id}/webhook-bindings/{binding_id}"),
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/webhook-bindings"),
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/start-form"),
]


@pytest.mark.parametrize("method,path", SLICE_4C3)
def test_slice_4c3_routes_name_their_answer(method: str, path: str) -> None:
    responses = schema()["paths"][path][method]["responses"]
    ok = next(code for code in responses if code.startswith("2"))
    body = responses[ok]["content"]["application/json"]["schema"]
    assert "$ref" in body or "$ref" in body.get("items", {}), body


def test_a_schedules_uncounted_span_keeps_its_wire_names() -> None:
    """`from` and `class` are Python keywords: the model aliases them, and the schema says the names on the wire."""
    span = schema()["components"]["schemas"]["UncountedOut"]
    assert sorted(span["properties"]) == ["class", "from", "reason", "to"]
```

At the end of `backend/tests/apps/api/test_webhooks_api.py`, add:

```python
async def test_a_filters_values_keep_their_types_through_the_typed_answers(
    keyed_app, tenant, owner_sessionmaker, api_settings
) -> None:
    """A clause's value is typed (`1`, `true`, `"1"` and null are four values): the named answers (4c-3a ruling 5)
    give each back as it was written, never coerced to another member of the union."""
    ctx, wf = tenant
    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    clauses = [{"pointer": "/a", "value": 1}, {"pointer": "/b", "value": True}, {"pointer": "/c", "value": "1"},
               {"pointer": "/d", "value": None}]  # fmt: skip
    made_binding = await editor.post(url(ctx, f"/webhook-endpoints/{endpoint['id']}/bindings"),
                                     json={"workflow_id": str(wf), "filter": clauses})  # fmt: skip
    assert made_binding.status_code == 201, made_binding.text
    listed = (await editor.get(url(ctx, f"/webhook-endpoints/{endpoint['id']}/bindings"))).json()["bindings"]
    by_workflow = (await editor.get(url(ctx, f"/workflows/{wf}/webhook-bindings"))).json()["bindings"]
    for answer in (made_binding.json()["filter"], listed[0]["filter"], by_workflow[0]["filter"]):
        assert answer == clauses and [type(c["value"]) for c in answer] == [int, bool, str, type(None)]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --frozen pytest -q tests/apps/api/test_openapi.py tests/apps/api/test_webhooks_api.py`
Expected: 15 failed: the 14 routes answer an unnamed object, and `UncountedOut` doesn't exist. The filter test passes
already (the dicts pass through untyped): it guards that the typed answers keep the values' types.

- [ ] **Step 3: The models, and each route's**

At the end of `backend/src/dewpoint/apps/api/responses.py`, add:

```python
class UncountedOut(_Answer):
    """A span of a schedule's life whose missed firings aren't counted (D3f): possibly missed, unknown, or pending
    until its count is read. `from` and `class` are Python keywords, so the fields are aliased to them."""

    from_: str = Field(alias="from")
    to: str | None  # null while it's open
    class_: Literal["possibly_missed", "unknown", "pending"] = Field(alias="class")
    reason: str


class ScheduleOut(_Answer):
    """A schedule (engine 2b spec §8.2), never its input; its sync's state and its missed-firing accounting (D3f)."""

    id: str
    workflow_id: str
    cron: str | None  # a cron, or
    every_s: int | None  # an interval, with its offset
    offset_s: int
    time_zone: str  # a cron's; an interval has none
    catchup_window_s: int
    mode: Literal["live", "simulate"]
    enabled: bool
    generation: int  # raised by every change
    synced_generation: int  # the last the sync confirmed; 0 before its first
    misses: int
    missed_while_created: int
    misses_read_at: str | None
    accounting_complete: bool
    uncounted_intervals: list[UncountedOut]
    sync_error: str | None  # `temporal_refused` or `sync_failed`: its last sync failed, retried after a minute
    sync_error_at: str | None  # when (4c-3a ruling 6)
    never_unpaused: bool  # nothing ever unpaused it: it never fired (4c-3a ruling 6)
    created_at: str
    updated_at: str


class SchedulesOut(_Answer):
    schedules: list[ScheduleOut]


class EndpointOut(_Answer):
    """A webhook endpoint (engine 2b spec §8.3), never its secret, its digest or its dedupe key. `path` is relative:
    its URL is this path on the deployment's webhook address."""

    id: str
    name: str
    enabled: bool
    auth: Literal["bearer", "hmac"]
    signature_header: str | None
    timestamp_header: str | None
    tolerance_s: int
    allowlist: list[str]
    body_limit: int
    id_source: Literal["pointer", "header", "none"]
    id_pointer: str | None
    id_header: str | None
    events_pointer: str | None
    trigger: str | None  # the trigger type it was made for; null: another sender (4c-3a ruling 1)
    path: str
    pending_events: int
    pending_bytes: int
    retained_events: int
    retained_bytes: int
    created_at: str | None


class EndpointCreatedOut(EndpointOut):
    secret: str  # shown this once


class EndpointsOut(_Answer):
    endpoints: list[EndpointOut]


class SecretOut(_Answer):
    id: str
    secret: str  # shown this once


class FilterClauseOut(_Answer):
    pointer: str
    value: str | int | bool | None  # typed: `1`, `true` and `"1"` are three values


class WebhookBindingOut(_Answer):
    id: str
    endpoint_id: str
    workflow_id: str
    filter: list[FilterClauseOut]  # all must hold; none: every event
    enabled: bool


class WebhookBindingsOut(_Answer):
    bindings: list[WebhookBindingOut]


class BindingEndpointOut(_Answer):
    """What a workflow's Triggers panel shows of a binding's endpoint (B13; 4c-3a ruling 2)."""

    id: str
    name: str
    enabled: bool
    auth: Literal["bearer", "hmac"]
    path: str
    trigger: str | None


class WorkflowBindingOut(WebhookBindingOut):
    endpoint: BindingEndpointOut


class WorkflowBindingsOut(_Answer):
    bindings: list[WorkflowBindingOut]


class StartFieldOut(_Answer):
    """A start form's field (engine 2b spec §7.7). A key it doesn't have is left out of the answer (the route excludes
    what's unset): a sensitive field's default and enum are masked, never sent."""

    name: str
    type: Any  # its schema's `type`: a name, a list of names, or none
    required: bool
    sensitive: bool
    title: str | None = None
    description: str | None = None
    enum: list[Any] | None = None
    default: Any = None
    default_masked: bool | None = None
    enum_masked: bool | None = None
    picker: dict[str, Any] | None = None


class CsvColumnFormOut(_Answer):
    header: str
    name: str
    type: str
    required: bool
    sensitive: bool
    default: Any = None  # left out unless declared
    values: list[str] | None = None  # a choice's; left out otherwise


class CsvFormOut(_Answer):
    max_rows: int
    max_bytes: int
    columns: list[CsvColumnFormOut]


class StartFormOut(_Answer):
    """The active version's input, as a form: what a schedule's input is entered on (4c-3a ruling 5)."""

    workflow_id: str
    version_id: str
    fields: list[StartFieldOut]
    csv: CsvFormOut | None
```

In `backend/src/dewpoint/apps/api/routes/schedules.py`, import `from dewpoint.apps.api.responses import ScheduleOut,
SchedulesOut` (after `from dewpoint.apps import schedules`), and the decorators become:

```python
@router.post("/t/{tenant_id}/workflows/{workflow_id}/schedules", status_code=201, response_model=ScheduleOut)
@router.get("/t/{tenant_id}/workflows/{workflow_id}/schedules", response_model=SchedulesOut)
@router.get("/t/{tenant_id}/schedules/{schedule_id}", response_model=ScheduleOut)
@router.patch("/t/{tenant_id}/schedules/{schedule_id}", response_model=ScheduleOut)
```

(each on its own route: create, list, read, update; delete keeps its 204).

In `backend/src/dewpoint/apps/api/routes/webhooks.py`, import (before `key_unusable`'s import):

```python
from dewpoint.apps.api.responses import (
    EndpointCreatedOut,
    EndpointOut,
    EndpointsOut,
    SecretOut,
    WebhookBindingOut,
    WebhookBindingsOut,
    WorkflowBindingsOut,
)
```

and the decorators become (each on its route; the events, dead events, cancels and usage stay as they are, outside
4c-3):

```python
@router.post("/t/{tenant_id}/webhook-endpoints", status_code=201, response_model=EndpointCreatedOut)
@router.get("/t/{tenant_id}/webhook-endpoints", response_model=EndpointsOut)
@router.get("/t/{tenant_id}/webhook-endpoints/{endpoint_id}", response_model=EndpointOut)
@router.patch("/t/{tenant_id}/webhook-endpoints/{endpoint_id}", response_model=EndpointOut)
@router.post("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/secret", response_model=SecretOut)
@router.post(
    "/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings", status_code=201, response_model=WebhookBindingOut
)
@router.get("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings", response_model=WebhookBindingsOut)
@router.get("/t/{tenant_id}/workflows/{workflow_id}/webhook-bindings", response_model=WorkflowBindingsOut)
@router.patch("/t/{tenant_id}/webhook-bindings/{binding_id}", response_model=WebhookBindingOut)
```

In `backend/src/dewpoint/apps/api/routes/run_requests.py`, import `from dewpoint.apps.api.responses import
StartFormOut` (after `from dewpoint.apps import admission, cancels`), and the start form's decorator becomes:

```python
@router.get(
    "/t/{tenant_id}/workflows/{workflow_id}/start-form", response_model=StartFormOut, response_model_exclude_unset=True
)
```

Check against the installed packages before relying on them: that a response model's `Field(alias=…)` field is
filled from the route's dict by the alias and serialized by it (`response_model_by_alias` defaults to true), and that
`response_model_exclude_unset` leaves a key the route didn't give out of the answer (FastAPI's `routing.py`).

- [ ] **Step 4: Run them to see them pass**

Run: `uv run --frozen pytest -q -n auto tests/apps/api/test_openapi.py tests/apps/api/test_webhooks_api.py tests/apps/api/test_schedules_api.py tests/apps/api/test_csv_starts_api.py tests/apps/api/test_run_requests_api.py tests/apps/api/test_schedule_checks_api.py`
Expected: every test passes. Each route's own tests now go through its model: an answer that drifts from its model
fails them.

- [ ] **Step 5: Lint, types, commit**

Run ruff (format and check) and mypy as "How to run things" says.
Expected: clean.

```bash
git add backend/src/dewpoint/apps/api/responses.py backend/src/dewpoint/apps/api/routes/schedules.py \
  backend/src/dewpoint/apps/api/routes/webhooks.py backend/src/dewpoint/apps/api/routes/run_requests.py \
  backend/tests/apps/api/test_openapi.py backend/tests/apps/api/test_webhooks_api.py
git commit -m "feat(api): named answers for the trigger routes and the start form

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The OpenAPI document and the client's types

**Files:**
- Modify: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts` (regenerated)
- Modify: `frontend/src/routes/editor/check.test.ts`, `frontend/src/routes/editor/DeclassifyPanel.test.tsx`,
  `frontend/src/routes/editor/ProblemsPanel.test.tsx`

**Interfaces:**
- Consumes: the schema after Tasks 3–8.
- Produces: `components["schemas"]` for every new model; `Validation` (`lib/workflows.ts`) gains `schedule_breaks`.

- [ ] **Step 1: Regenerate, and see the client's type check fail**

From `backend/`: `uv run --frozen dewpoint api openapi > ../frontend/src/api/openapi.json`. From `frontend/`:
`npx --offline pnpm@12.6.0 gen:api`, then `npx --offline pnpm@12.6.0 typecheck`.
Expected: three errors, each a typed validation answer missing `schedule_breaks` (`check.test.ts`,
`DeclassifyPanel.test.tsx`, `ProblemsPanel.test.tsx`).

- [ ] **Step 2: The fixtures**

Each gains `schedule_breaks: []` beside its `conditional_steps: []`:
- `check.test.ts`, in `answer`: `conditional_steps: [], schedule_breaks: [],`
- `DeclassifyPanel.test.tsx`, in `check`: `valid: false, draft_revision: 1, expressions: [], conditional_steps: [],
  schedule_breaks: [],` and the `taint` on the next line (the line stays within 120 characters);
- `ProblemsPanel.test.tsx`, in `VALIDATION`: `…, conditional_steps: [], schedule_breaks: [],`.

- [ ] **Step 3: The client's checks**

From `frontend/`: `check:api`, `typecheck`, `lint`, `test`.
Expected: clean; the unit suite passes whole (828 at main's aed887f8).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/openapi.json frontend/src/api/schema.d.ts frontend/src/routes/editor/check.test.ts \
  frontend/src/routes/editor/DeclassifyPanel.test.tsx frontend/src/routes/editor/ProblemsPanel.test.tsx
git commit -m "chore(api): the OpenAPI schema and the client's types for 4c-3a

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Every check, the ledger, the final checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md` (§5: B13's row says where it was built)

- [ ] **Step 1: The whole backend suite, the frontend's checks, CodeQL**

Ask the owner before the backend suite (about 12 minutes with `-n auto`). Then:
- `uv run --frozen pytest -q -n auto` from `backend/` (with the CEL gate tests too, as CI runs them);
- ruff (format and check), mypy, the import linter;
- the backend's OpenAPI diff against `frontend/src/api/openapi.json` (CI's step), and from `frontend/`: `check:api`,
  `lint`, `typecheck`, `test`, `build`;
- local CodeQL on the branch's head (`scratchpad/codeql/scan.sh <sha>`): no new alert.

Expected: every one passes. A failure is read and fixed test-first, or reported as it is: never a claim that every
check passes when one didn't. The browser gate isn't run: no screen changed (the frontend's unit suite and build
are).

- [ ] **Step 2: The outline's row**

In the outline's §5 table, B13's row adds "Built in 4c-3a: `GET …/workflows/{workflow_id}/webhook-bindings`, each
binding with its endpoint".

- [ ] **Step 3: The ledger**

Append `### 4c-3a, milestone 3 and the final checkpoint (date)`: the tasks' commits, each check's result as run (the
suite's counts), every mid-slice ruling, anything deferred. Commit (`docs(editor-4): 4c-3a final checkpoint`).

- [ ] **Step 4: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch against this plan (its Review Focus first),
the outline's 4c rows and the ledger's rulings 68, 71, 74 and 96. Critical and important findings are fixed
test-first, once; minor ones are listed. Then **stop**: the summary to the owner names what's built, the checks as
run, the rulings proposed and made, and asks for the owner's word on push and a PR (nothing is pushed before it). CI
on the PR runs the backend (about 12 minutes), the frontend, CodeQL and the Compose e2e: say so before pushing.
