# Editor UI 4e-1: the Runs page, a run's page, and cancel (design)

Status: the design the owner accepted on 2026-10-15 ("Yes to all four; commit the spec"). Their answers are in §3
and §8. The D8 mockups were signed off at canvas version 9. Base: `origin/main` fccd09f1 (ENGINE_ABI 9; migrations to 0072).

Sources:
- the editor outline (`docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md`: §1 screens 1f and 1g; §2 "4e — runs";
  §5 B4a, B4b and B10; D2, D3, D5, D8, D16, D20, D21, D23);
- the editor ledger (`docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`);
- the 4d-1 design (`docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md`: §3 B4b, §6.6 the readers, §7 the
  tags);
- the engine 2b spec (§7.7, the runs list; §10.1, retention).

The mockups are the Design canvas "4e-1 Runs Mockups", version 9. It has 8 boards, each in light and dark, and two
true 320 px boards. The research behind this design (R1 backend, R2 frontend, R3 design sources) sits outside the repo,
in the owner's notes.

## 1. What 4e-1 is

- **The Runs page** lists a tenant's runs, newest first. It can be filtered by workflow, status, trigger, mode and when
  they started. It is read again every 5 s while visible, and a failed run shows its error in the list.
- **A run's page** shows the version (or draft snapshot) it ran, on the read-only canvas:
  - each step's result as tags beside its card, from a server summary;
  - a loop's iterations, paged;
  - a step's result in the editor's side drawer: status, attempts, timing, error, input and output previews, its
    sub-run;
  - the run's input as stored, redacted, and a CSV run's file.
- **Cancel** for a run that's waiting or running. A live run asks first.
- Live is orange (D3); simulated is slate with the hatch (D2), as 4d-1 drew it.

Out of scope:
- **4e-2:** the run form with CSV upload and mapping, and the re-run dialog, D13 (B11 and B14 are 4e-2's).
- **Slice 5:** approvals ("Awaiting approval") and "Explain this failure".
- Runs of other tenants.

## 2. Two plans, one design

| Plan | Contents | ABI | Migration |
|---|---|---|---|
| 4e-1a, backend | B10, a run's own facts, the step reads for every run, typed answers (§4) | none | 0073, two nullable columns (§4.3; the owner's slot, §8) |
| 4e-1b, UI | the screens of §5, built against the signed-off boards | none | none |

Each plan has its own branch and PR (D26). 4e-1b needs 4e-1a merged. 0073 follows the rules 0071 and 0072 did:
- the online-migration helper;
- grants last;
- the privilege reference regenerated.

## 3. The owner's answers (2026-10-15)

1. **Shape: read first, then start.**
   - 4e-1 is the Runs page, a run's page and cancel.
   - 4e-2 is the run form with CSV mapping and the re-run dialog.
   - Each gets mockups, a spec, a backend plan and a UI plan.
2. **The list shows a failed run's error.** It shows the code and the message, which the list already returns. There
   is no "N of M" Steps column and no totals line.
3. **Which runs are listed.** Live runs, and simulations of a published version, the simulated ones tagged. Draft
   simulations appear only when the Mode filter chooses them.
4. **A run's name is the first 8 characters of its id.** Its page shows the whole id, with Copy id.
5. **"Ran out of time" everywhere.** The Simulation panel's "Deadline exceeded" changes in 4e-1b.
6. **A run's page is laid out like the editor:**
   - the app header and the compact rail;
   - a bar;
   - the read-only canvas;
   - the step's result in the editor's side drawer.

   A failed run opens on its failed step.
7. **Cancel asks first for live runs only.**
8. **Times are in the person's own zone,** with the full date and zone on hover.
9. **D8 signed off** at canvas version 9, as drawn. A live run's banner doesn't name its connections.

## 4. Backend (4e-1a)

### 4.1 Typed answers

Every run route the UI reads gets a `response_model`, so the generated client stops typing them as unknown maps (B1:
"as its slice adopts it"):
- the list;
- a run;
- cancel;
- §4.4's reads;
- the input read-back.

`check:api` regenerates `schema.d.ts`. No answer's existing field changes meaning; §4.5 removes two.

### 4.2 The list (B10)

`GET /t/{tenant}/runs` keeps its shape: an array of items, newest first by `(queued_at, id)`, with the
`before` + `before_id` cursor taken from the last item. It also keeps its retention cut. It gains these query
parameters:

| Parameter | Values | Meaning |
|---|---|---|
| `workflow_id` | a workflow id | as today |
| `status` | `waiting`, `running`, `succeeded`, `failed`, `deadline_exceeded`, `cancelled`, `didnt_start` | one value. `waiting` is a request queued or starting; `didnt_start` is one refused or dead. Applied to both branches of the list's `UNION ALL` (a run's status, or an unstarted request's) |
| `mode` | `live`, `simulate` | absent: both |
| `draft` | `exclude` (the default), `only`, `include` | draft simulations (a `draft_snapshot_id`) |
| `source` | `manual`, `rerun`, `schedule`, `webhook`, `dev` | the request's source |
| `since` | an ISO time | items queued at or after it |

`draft=exclude` by default changes today's answer, which lists draft simulations. No caller in the repo relies on
that. The Mode menu maps onto these parameters:

| Menu choice | Parameters |
|---|---|
| Live and simulated | `mode` absent, `draft=exclude` |
| Live | `mode=live` |
| Simulated | `mode=simulate` |
| Draft simulations | `draft=only` |
| Everything | `draft=include` |

Each item gains:
- `workflow_name`;
- `started_by`: the requesting user's email for `manual` and `rerun`, else null. Users have only an email; the boards'
  "Nadia Martin" becomes it;
- `trigger`, as below;
- `cancel_requested_at`.

The `trigger` field:

```
{ "source": "schedule", "schedule": { "cron", "every_s", "offset_s", "time_zone" } | null,
  "endpoint": { "name" } | null, "rerun_of": "<run id>" | null }
```

The schedule's own timing is sent, and the UI words it with the function the Triggers panel already uses. The fields
are null where §4.3's columns are null (older requests), or when the schedule or endpoint was deleted. Labels are read
in one join per page, never per item.

Indexes: the plan runs `EXPLAIN` on a tenant seeded with 100,000 items for each filter and their combinations. It adds
an index in 0073 only where a filter scans. Its tests count rows read, not time.

### 4.3 What a run says about itself

Migration 0073 adds two nullable columns to `run_requests`. Both are plain ids, never secret. Today the trigger exists
only inside the encrypted envelope, and the re-run link only in the audit entry.
- `rerun_of uuid`: the run a re-run repeats. Admission sets it for `source = rerun`.
- `trigger_id uuid`: the schedule's id for `schedule`, the webhook endpoint's id for `webhook`. Set at admission, null
  otherwise.

Older requests keep both null. The UI then shows the kind alone ("Schedule", "Re-run"). The columns are added without a
default (a metadata change). The roles that insert requests write them; the API reads them. Erasure deletes them with
their rows.

A run's answer (`GET /t/{tenant}/runs/{run_id}`) carries:
- the list item's fields above;
- `version_id` or `draft_snapshot_id`, with `draft_revision` for a draft;
- `outcomes_recorded`: false when its graph's `engine_abi` predates B4b (< 9);
- `parent`, `{run_id, step_id, iteration_key}`, for a sub-run;
- the CSV record (`mapping, headers, row_count, skipped, errors, error_count`), as today.

The graph comes from B4a's version route, or from the draft snapshot route for a draft simulation (4d-1b).

**The input, read back** (`GET /t/{tenant}/runs/{run_id}/input`, `run.view`) is 4d-1b's read-back, generalised from
draft simulations to every request:
- the input as the request's envelope stored it;
- every value under a sensitive position replaced by `"[redacted]"`;
- `read_back: kept | absent | unreadable`.

`absent` means it passed its retention cutoff. `unreadable` means its key is gone, during an erasure (503
`key_unusable` is answered as `unreadable`, never an error page).

### 4.4 A run's steps, for every run

4d-1b's draft-only readers (`apps/step_summary.py`) serve every run:
- `GET /t/{tenant}/runs/{run_id}/steps` is the summary. Per step of the run's graph (or a step test's target alone):
  `origin`, `instances`, `statuses`, `ports` and the single instance's `final`, in run order. Tags come from it, never
  from a partial page.
- `GET /t/{tenant}/runs/{run_id}/steps/{step_id}/instances?within=&offset=&limit=` gives each instance's final attempt,
  in iteration order, paged (limit ≤ 100). Each carries `child_run_id` when it started a sub-run.
- `GET /t/{tenant}/runs/{run_id}/steps/{step_id}/attempts?iteration=<key>` gives every attempt of one instance, in
  order. It is bounded by the step's retry maximum.

The draft simulation routes keep their paths (the editor reads them) and share this code.

Origins (§5.4 words them):

| Run | Step | Origin |
|---|---|---|
| simulated (published or draft) | any | 4d-1b's codes, unchanged |
| live | a plugin step whose finals include `outcome_unknown` | `may_have_been_sent` |
| live | a plugin step whose finals include `applied` (and none unknown) | `sent`: every live action that called its connection, reads included (a successful attempt records `applied`) |
| live | a control step, or a plugin step whose finals have no outcome (it failed before sending, or the service refused it) | null: no origin tag |

The codes for steps that didn't run stay as they are: `skipped`, `not_started`, `cancelled`, `not_reached_yet`,
`didnt_run`, `not_recorded`. `not_recorded` also covers a step without a row after the end of a run whose
`outcomes_recorded` is false.

Cost: the summary is one `GROUP BY` over each instance's final attempt. The plan pins it with a work-unit test on a
run of 100,000 instances (statements and rows read per call), and §5.3 polls it at most every 5 s.

### 4.5 A bounded run detail

`GET /runs/{run_id}` stops returning `steps` (every attempt, unpaged, up to 8 KiB of previews each) and `children`:
§4.4 replaces both. No caller in the repo reads them but the backend's own tests, which move to §4.4's reads.

The Workflows list's `last_run` gains its run's `id`, so the list can link to it.

### 4.6 Permissions, retention, erasure

- Reads need `run.view` (every role). Cancel needs `run.cancel` (operator and up).
- A run past its retention cutoff answers 404 on every route above, as the list leaves it out.
- During an erasure:
  - cancel answers 409 `tenant_erasing`;
  - after the key stage, the input read-back says `unreadable`;
  - a CSV run's detail (whose record is decrypted) answers 503 `key_unusable`, which the page words (§5.5).
- Cancel keeps its answers, typed: 200 `cancelled` (a request that hadn't started), 202 `requested`.

## 5. The UI (4e-1b), per the signed-off boards

### 5.1 Where it lives

Routes:
- `/t/$tenantId/runs`, with the filters in its search parameters so a link keeps them;
- `/t/$tenantId/runs/$runId`.

Both are loaded lazily, in their own chunks. The canvas they share with the editor must not grow the editor's chunk. If
the shared module changes the editor's asset split, which an e2e test pins at two `Editor-*` files, the plan updates
that test with the build's evidence.

Runs joins the rail after Workflows (ledger ruling 27). Entry points:
- the rail;
- a workflow's "Runs" link in the editor's toolbar (the list with its filter set);
- the Workflows list's last-run cell (that run);
- the Simulation panel's run id (that run's page).

### 5.2 The Runs page (boards Main, ListStates)

- **Filters** are "Label · Value ▾" menus, one choice each; a set filter is outlined in the accent.
  - Workflow: a searchable list.
  - Status: Any; Waiting (queued or starting); Running; Succeeded; Failed; Ran out of time; Cancelled; Didn't start
    (couldn't start or refused).
  - Trigger: Any, By hand, Re-run, Schedule, Webhook (`dev` shows under Any only).
  - Mode: §4.2's five choices; "Live and simulated" is the default.
  - Started: last hour, 24 hours (the default), 7 days, 30 days, all kept.
- **Columns:**
  - Run: the short id, a link;
  - Workflow;
  - Status: a chip, plus the hatched "Simulated" or "Draft simulation" chip;
  - Trigger: the kind, then the starter's email (by hand), the schedule's time, the endpoint's name, or "of <id>" (a
    re-run);
  - Started: the started time, else the queued time;
  - Duration;
  - Error: the code in mono, with its message under it.
- **Reading:**
  - The first page is read again every 5 s while the page is visible (TanStack pauses when hidden). New items appear
    at the top, and items are de-duplicated by id across pages.
  - Pages loaded with "Load more" aren't polled.
  - "Updates every 5 s" sits by the title, never "Live". A failed refresh keeps the list and says "Couldn't be
    refreshed · as of 10:02:07", with Try again.
- **States, as drawn:** nothing matches (with Clear the filters), no runs yet, reading, the first read failed, and no
  older runs kept.

### 5.3 A run's page (boards RunFailed, RunRunning, RunLoop)

- **The bar:**
  - ← Runs, the workflow's name, "run <8>" and Copy id;
  - the status chip; Live (orange) or Simulated / Draft simulation (hatched);
  - the version or draft revision, the trigger, the start, the duration;
  - "Open the workflow" ("Open in the editor" for a draft simulation);
  - "Cancel the run" (`run.cancel`, while waiting or running).

  There's no Re-run (4e-2) and no "Explain this failure" (5).
- **The banner:**
  - live: "Live run. It acted for real: steps marked sent called their connections.", orange;
  - simulated: 4d-1c's hatched banner;
  - a draft simulation's names its revision.
- **The canvas:**
  - the version's graph, read-only (`Canvas` with `editable={false}`);
  - the keyboard of D16, moved out of `Editor.tsx` into a hook both use;
  - the start card carries `input` and opens the Start drawer (§5.4).
- **Tags** are 4d-1c's grammar and placement (beside the card where nothing is there, else under it; under it at narrow
  widths):
  - the status;
  - "attempt N of M" past the first;
  - a single instance's duration;
  - a failed instance's error code;
  - the origin (§4.4);
  - ports ("→ true ×17");
  - a loop's totals ("120 instances: 14 succeeded · 3 failed · 103 skipped").

  No green edges and no halo. A failed card keeps its outline: its tags say it failed. The open card has the accent
  outline.
- **The drawer** has Result (the default) and Setup (read-only).
  - Result shows:
    - the status, "attempt N of M", the times;
    - the error (code and message);
    - the attempts, one row each (§4.4's attempts read);
    - the last attempt's input and its output, with `redacted` and `truncated` marks (D20: never dots);
    - a sub-run's link.
  - A loop's drawer pages its iterations four at a time, with Open.
  - A step inside a loop has 4d-1c's iteration picker (the first 50, and an iteration opened from the loop's list) and
    Show.
- **Reading:**
  - While the run hasn't ended, its state is read every second, backing off to every 5 s, paused while hidden; the
    summary with it, at most every 5 s.
  - Once it ends, both are read once more 5 s later: step rows and sub-runs can still settle. After that, they're
    read only on focus or reload.
  - An open drawer's instances and attempts are read with the summary while the run runs.
- **Cancel:**
  - a live run opens an alertdialog: "Cancel this run? It stops at its next step. What it already did against Mist
    and its other connections isn't undone." with Keep it running and Cancel the run;
  - a simulated run cancels at once;
  - then the "Cancel requested" chip shows, with "It's shown as cancelled once the server confirms it.";
  - a failure says "Couldn't cancel it. Try again.";
  - roles without `run.cancel` see no Cancel.

### 5.4 Runs that didn't run, and others (board RunOther)

- **Waiting to start:**
  - "Waiting to start · queued … Nothing has run yet.";
  - the canvas without tags;
  - Cancel.
- **Couldn't start and Refused:** the code, its words, the server's messages (up to 5) and "Nothing ran."
- **Older runs** (`outcomes_recorded` false): a strip, "This run is older than step-by-step results: a step it didn't
  record shows not recorded."
- **The Start drawer:**
  - the trigger, who, and when;
  - the input as read back (`kept`; `absent`: "Its input isn't kept any more. The run's steps and results still
    are."; `unreadable`, §5.5);
  - a CSV run's file: rows read, run and skipped, each skipped row's code (the first 100), and the mapping.
- **A run past retention, or an unknown id:** "This run isn't kept any more, or it never existed here.", with Back to
  Runs.

### 5.5 Words

One status vocabulary module (`lib/runStatus.ts`) serves the Runs page, a run's page, the Workflows list and the
Simulation panel:

| Status | Word | Look |
|---|---|---|
| queued | Queued | dashed neutral |
| starting | Starting | dashed neutral |
| running | Running | accent |
| succeeded | Succeeded | `--ok` |
| failed | Failed | `--danger` |
| deadline_exceeded | Ran out of time | `--danger` |
| cancelled | Cancelled | neutral |
| dead | Couldn't start | `--danger` |
| refused | Refused | `--danger` (the Simulation panel keeps "Not simulated" for its own refusals) |

Origins add to 4d-1c's words:
- "sent": live outline;
- "may have been sent": warn, dashed.

`key_unusable` is worded: "This run can't be read while the tenant is being erased."

### 5.6 Accessibility, 320 px

- WCAG 2.2 AA, light and dark, at 1280 and 320 px. The list's rows become a list below 640 px.
- One persistent status region per page announces changes ("Updated", "Run ended: failed"). A region mounted with its
  text isn't announced reliably (#112 minor 10).
- Focus goes to the drawer's heading when it opens, and back to its card on Close. Every control is named.

## 6. Testing

- **4e-1a:**
  - the list:
    - each filter and their combinations, across both branches of the `UNION ALL`;
    - the cursor under filters;
    - `draft`'s three values and the default;
  - `workflow_name`, `started_by` and `trigger` for every source, with older rows' nulls and a deleted schedule or
    endpoint;
  - 0073 up and down, and the privilege reference;
  - admission writing `rerun_of` and `trigger_id`;
  - §4.4 on live, simulated and draft runs:
    - every origin row of §4.4's table;
    - `not_recorded` both ways;
    - `child_run_id`;
    - the attempts bound;
  - the summary's work-unit test at 100,000 instances;
  - the input read-back's three states, retention included;
  - the bounded detail;
  - 404 past retention;
  - the erasure answers;
  - tenancy and RLS;
  - the role × endpoint matrix.
- **4e-1b:**
  - unit tests per surface, against typed fakes;
  - the Playwright gate (CSP, console, axe), light and dark at 1280 and 320 px, over each board's state on the Compose
    stack. Its runs are seeded through the API: a published workflow of control steps only, run live (nothing leaves
    the stack, D24) and simulated; a failing run (a `fail` step); and a loop.

## 7. Risks

- **The summary's cost on large runs at the polling cadence.** The work-unit test pins it. Polls are capped at 5 s and
  stop after the end.
- **The status filter over the `UNION ALL`.** The plan's `EXPLAIN` decides any index.
- **A starter's email is shown to every role with `run.view`, viewers included** (accepted, §8).
- **Removing `steps` and `children` from the run detail** is an API change. There's no caller in the repo but the
  backend's tests (accepted, §8).
- **The canvas shared with the editor:** the chunk split, and the keyboard hook's extraction under the editor's tests.
- **Copy id** needs a secure context. The app is served over TLS or on localhost.

## 8. The owner's answers at review (2026-10-15)

The owner: "Yes to all four".

1. **Accepted. Migration slot 0073** for `rerun_of` and `trigger_id`.
2. **Accepted. Who started a run is shown as their email to every role with `run.view`.** Runs are team records,
   and Members already shows emails to managers.
3. **Accepted. The run detail loses `steps` and `children`,** replaced by the paged reads.
4. **Accepted. "sent" goes on every live action that called its connection, reads included.** This corrects the
   RunFailed board, where `get_device` has no tag.
