# Editor UI 4f-1: the message composer — design

**Status:** written 2026-10-20 for the owner's review. D8 signed off on the Design canvas "4f-1 Message Composer
Mockups", version 9 (https://claude.ai/artifact/7u8NCd68oNXBX7FXVvaDYc): boards Main, Previews, States, OtherSteps,
MainDark, MoreStates, Narrow320Light, Narrow320Dark.

**Sub-project 4 (editor UI), slice 4f** (outline `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md` §2, 4f):
"the Mist picker …, nested update, the message composer with Slack, Teams and Google Chat previews, and the run
form's connection-scoped pickers". 4f is split in three (§2); this is the first.

## 1. What 4f-1 is

The eight steps that send a message share one model, the SDK's `Message` (`backend/src/dewpoint/sdk/messages.py`,
plugins-3 D18): Slack, Teams, Google Chat, a webhook's `send_message`, email, syslog, PagerDuty's `trigger_alert` and
ServiceNow's `create_incident`. Today the drawer shows each as the generic form: `text` and the connection on Setup,
the title, the fields' and links' lists and the severity on Options, one line of text, no preview.

4f-1 gives them a composer: the message written in one place on Setup, its text on several lines with values from
earlier steps, its fields and links, its severity, and for Slack, Teams and Google Chat a preview of how the message
will look, with what the target would cut said before the step runs.

Not in 4f-1:
- the Mist step (4f-2) and the run form's pickers (4f-3);
- connection forms for Slack, Teams or Google Chat (4g, #59: until then such a connection is added through the API);
- previews for email, syslog, PagerDuty and ServiceNow (§5.5);
- a preview with a run's real values: a value shows where it comes from (§5.5).

## 2. Three slices, in this order

1. **4f-1, the message composer** (this design).
2. **4f-2, the Mist step:** a Resource → Action chooser over the 294 Mist types; labelled path fields whose live
   choices also take values from earlier steps (amending ledger ruling 127); an update's body editor (merge or
   replace; Keep, Set or Clear per top-level setting; Find a setting over the body's settings, by name and
   description). No merged-body preview (it needs a live read of Mist: with 4d-2).
3. **4f-3, the run form's pickers:** a start form's `picker` field in the run, schedule and Simulate forms, and
   adding a picker to a workflow's input in the Triggers panel.

The composer settles the two editor changes the later slices reuse: widget hints from the plugins (§4) and text on
several lines with values (§5.2).

## 3. The owner's answers (2026-10-20)

1. **"Research first, then propose":** three research notes (`~/4_dev/mist_dewpoint-4f-notes`, R1 plugins and API, R2
   frontend, R3 design sources), then a proposal.
2. **The order:** composer, Mist, pickers.
3. **Previews are rendered in the browser:** each target's rules mirrored in TypeScript, held to the plugins' own
   renderers by shared cases (§4.2). No server preview route.
4. **The plugins say which steps get which widget** (display hints, `x-widget`), never the frontend recognising a
   config's shape.
5. **The plugins' 3b-1 rulings are signed off as merged** (the Mist pickers for site and organisation ids only; the
   update contract: a top-level `body`, merge or replace, `clear`). The plugins-3 ledger records no sign-off for them;
   4f-1's ledger task records it there.
6. **Round 1 of the mockups approved** ("approved"), with the seven calls drawn: the message kept together on Setup;
   text on several lines; a value shown as where it comes from; a link's address checked as it's typed; the severity
   as four choices; previews for Slack, Teams and Google Chat only (the webhook's JSON, the others none); over a
   target's limit a warning, never an error.
7. **D8 signed off** at version 9 ("signed off, write the spec").
8. **Formulas kept where useful** (after the builder check, AskUserQuestion): the severity, the fields and the links
   each keep a Fixed / Formula switch, so a formula can compute them from data (an alarm's level, an earlier step's
   list); the title, the text, and each field's or link's label and value take values from earlier steps.

## 4. Backend

### 4.1 The message widget's hint

The SDK's `Message` model carries a display hint at its root: `x-widget: "message"`
(`model_config = ConfigDict(extra="forbid", json_schema_extra={"x-widget": "message"})`). Every config built on it
(`class SendConfig(Message)`) has the hint at its schema's root, so the eight steps get the composer, and so does a
third-party plugin that builds its config on the SDK's message (built-in widgets only, arch §101).

- `x-widget` is a display annotation (`backend/src/dewpoint/engine/registry/catalog.py:32`): the contract hash drops it
  from every schema object, the root included (`_schema_contract`). No version changes; the registry refreshes a
  version's display metadata in place (plugins-3 ledger, 3a-2: "both are display metadata, so the editor … can rename
  them without a new version").
- To verify at plan time against the installed pydantic: a model's `json_schema_extra` reaches a subclass's schema
  root; the eight manifests carry the hint; their contract hashes are unchanged.
- The name is `message`. Ledger ruling 100 named `message-blocks` as an example of a 4f widget; it isn't emitted
  anywhere, so the shorter name costs nothing.

### 4.2 The renderers' shared cases

The previews mirror the Slack, Teams and Google Chat renderers (`plugins/slack/__init__.py` `render()`,
`plugins/teams/__init__.py` `render()` with its `LEVELS`, `plugins/google_chat/__init__.py` `render()` with its
`LEVELS` and `NEUTRAL`) and the SDK's `cut()`. To keep the two honest:

- a fixed set of messages (empty title, a long text, escapes, multi-byte text, `<` `>` and `|`, 25 fields, 10 links,
  each severity, each cut level of Teams and Google Chat) lives in one JSON file of cases in the frontend's test
  support, with, for each target, the body the Python renderer returns and the values it cut;
- a backend command writes the expected bodies from the plugins' own `render()`; a backend test fails when the file
  differs from what the renderers return now (a renderer changed, the cases not regenerated);
- a frontend test holds each TypeScript renderer to the same file.

The file holds no secret and no real data (made-up messages, D24).

### 4.3 Nothing else changes

No route, no migration, no ABI change, no new version of any step. The link and email checks stay pydantic validators
(a `pattern` on `Link.url` would change the contract hash): the composer checks a link as it's typed (§5.3).

## 5. The UI, per the signed-off boards

### 5.1 Where the composer shows (Main, OtherSteps)

A step whose config schema has `x-widget: "message"` at its root shows the composer:

- **Setup:** the connection and the step's other required fields as today (email's To), then **Message**: severity,
  title, text, fields, links, in that order, then the preview (§5.5). The message's parts stay together on Setup,
  optional ones included: ledger ruling 98 (Setup holds the required fields) is amended for a message.
- **Options:** the step's other optional fields as today (ServiceNow's urgency, impact, assignment group…; PagerDuty's
  dedup key…), with "The message is on Setup; what only <target> takes stays here."
- The model's five properties are the widget's: `title`, `text`, `fields`, `links`, `severity`. A config with the hint
  but without `text` falls back to the generic form (ruling 100).
- **Formulas (§3, answer 8):** the severity, the fields and the links each keep today's Fixed / Formula switch (ledger
  101), beside their label: Fixed shows the composer's control (the four choices, the rows), Formula today's formula
  field. A part held as a formula shows "Computed when the step runs" in the preview in its place, and the cut maths
  leave it out. A part the composer can't draw as its own control (a value of a kind it doesn't take there) shows
  today's control for that part, unchanged: opening the drawer never rewrites a draft (ledger 102).

### 5.2 The text and the title (Main, MoreStates)

- **Title:** optional, one line, values allowed (today's pill editor). Its hint names what it becomes where it matters
  ("optional · the email's subject").
- **Text:** required, on several lines, values allowed. Each line is the pill editor's row; Enter splits the line at
  the caret, Backspace at a line's start joins it to the one above, / or ＋ Data opens the data from earlier steps under
  the field (ledger 126) and Enter there adds the value at the caret. The text is stored as it's stored today (a
  template value), its newlines kept. No `contenteditable`: ruling 125's reason holds; the ruling is amended only in
  that the text field takes newlines.
- **A long run of written text** is split when it's saved: the engine takes a template's written text in parts of up to
  4,096 characters each (`engine/graph/values.py` `MAX_TEXT`, at most 100 parts), so the composer writes a longer run
  as several parts in a row, which reading joins back. Without it, a text holding a value would be refused at publish
  well under the model's 40,000 characters. The split is in the shared writer (`pills.ts` `valueOf`): every field
  that takes values gains it. To verify at plan time: the engine accepts adjacent written parts.
- Under the text: "Press / or ＋ Data to add a value; Enter starts a new line." and, for Slack, "118 characters,
  before its values. Slack shows up to 3,000." (the count of the escaped text, as the renderer counts it).
- The model's own bounds (title 1,000 characters, text 40,000) are the schema's: validate says them, as for any field.

### 5.3 Fields and links (Main, States)

- **Fields:** rows of a label and a value, each taking values from earlier steps; "2 of 25"; "＋ Add a field";
  each row's remove named "Remove field N". At 25 the add is disabled with "A message takes up to 25 fields: remove
  one to add another."
- **Links:** rows of a label and an address, each taking values; "1 of 10"; "＋ Add a link"; the same cap words for
  10.
- **Order:** each row keeps today's Move up and Move down (the order shows in the target: Slack's fields two to a row,
  the buttons left to right), beside its remove; at 320 px under the item, beside Remove. Edit as JSON isn't offered
  on these lists: a formula (above) computes a whole list.
- **A link's address is checked as it's typed:** an address that starts with written text must start with `http://`
  or `https://`; else "A link's address starts with http:// or https://." beside it (today a bad link passes publish
  and fails when the step runs). An address that starts with a value can't be checked before the run.

### 5.4 Severity

Four choices in a row, a radio group: Info, Success, Warning, Critical; Info by default (the model's). At 320 px, two
rows of two. Its Fixed / Formula switch beside its label (§5.1).

### 5.5 Previews (Previews, States, MoreStates, OtherSteps)

- **Slack, Teams, Google Chat:** "Preview in Slack" (or Teams, Google Chat) under the message, with "Laid out as
  Slack shows it. A value shows where it comes from until the step runs." The preview is the TypeScript mirror's
  output for the message, each value replaced by where it comes from (`check.site`), shown in the code face with a
  dotted underline. What it shows is what the renderer sends: Slack's bold title, text, fields two to a row, links as
  buttons, "Severity: warning"; Teams' card, fields as "label: value", links as buttons, the severity line; Google
  Chat's text, the title and labels in bold, links as linked words, `<` `>` as ＜ ＞, "Severity: warning".
- **The webhook's `send_message`:** "What it posts": the message as JSON, as written, nothing cut, values shown as
  where they come from.
- **Email, syslog, PagerDuty, ServiceNow:** no preview; one line says how the target sends it (email: "No preview: an
  email is plain text, its subject the title (or the text's first line), up to 200 characters."; the others: "No
  preview for <target>: it sends the same message in its own form, and Simulate step says what it would cut.").
- **What a target would cut,** computed by the mirror on the message with its values unresolved: said under the part
  it concerns ("3,214 characters. Slack shows the first 3,000 and ends them with "…".") and under the preview ("Slack
  will cut the text at 3,000 characters."); for Teams and Google Chat, the body's size against its budget and what
  would be shortened first ("About 31,000 bytes before its values: Teams takes 24,000. The text would be shortened
  first, then the fields' values."). A warning, never an error: the step publishes and the target shows the start.
- The preview follows every edit; it's a region named by its heading, and isn't announced as it changes.

### 5.6 Other states (States, MoreStates)

- **No connection of the type yet:** the connection's select is disabled with "No Slack connection yet: an admin adds
  one." The type is named by its label from `GET /api/v1/connection-types` ("Slack", "Microsoft Teams"), never its key
  (today's "No slack connection yet"). The message can still be written and previewed.
- **The text left empty:** "Give the text: a message needs it." (the required words of the drawer), when the step is
  checked; the preview says "Nothing to show yet: the message has no text."
- **Read only** (a version viewed, a role that can't edit): the message as written, values as pills, the preview kept;
  "Severity: warning · 2 fields · 1 link" summarises the rest.
- **Simulated** (Simulate step's Test tab, 4d-1): a message step's result says what it would cut in words, from its
  output's `truncated`, beside 4d-1's "Simulated. Nothing was sent." The output names the values cut, never their size
  or the level Teams or Google Chat used, so the sentence names the part and the target's limit where the mirror
  knows it: "Slack would cut the text at 3,000 characters."; "Teams would shorten the text to fit its 24,000 bytes.";
  "Google Chat would shorten the text to fit its 30,000 bytes."; for email, syslog, PagerDuty and ServiceNow, "<Target>
  would cut the text." The States board's "(3,214 with its values)" can't be had from the output, and resolving the
  template in the browser would repeat the engine: it's left out. The server renders the message; nothing new is
  asked of it.

### 5.7 Words

The copy is the boards'. The cut names (`title`, `text`, `fields[i].label`, `fields[i].value`, `links[i].label`,
`links[i]`, and ServiceNow's `description`) are worded "the title", "the text", "field 3's label", "field 3's value",
"link 2's label", "link 2 (left out)", "the description".

### 5.8 Accessibility, 320 px (Narrow320Light, Narrow320Dark, MainDark)

- WCAG 2.2 AA, light and dark, at 1280 and 320 px; targets at least 24 px, 44 px at 320.
- The message is a fieldset with the legend "Message"; the severity a radio group; each row's controls named by their
  row ("Field 1 label", "Remove field 1"); errors and warnings linked to their control (`aria-describedby`).
- At 320 px the drawer sits below the canvas (as today); each field and link is an item, its label and value stacked,
  "Remove" under them; the preview follows the message.
- No AI tells (`src/test/aiTells.test.ts`): the previews use the app's tokens, never a target's brand colours or
  emoji.

## 6. Testing

- **Backend:** the eight manifests carry `x-widget: "message"` at their config's root; their contract hashes are
  unchanged; the shared cases file matches each renderer's output.
- **Frontend, unit:** the widget chosen by the hint; Setup and Options as §5.1; the multi-line text (Enter, Backspace
  joining lines, a value added at the caret, newlines kept through save); fields and links with their caps; a link's
  check; the severity; each TypeScript renderer against the shared cases; the cut words; the previews' placeholders;
  the webhook's JSON; the no-preview lines; no connection, empty text, read only, simulated; 320 px. Fixture node types
  are made up (D24): a message-shaped type with the hint, never a real plugin's manifest copied.
- **Browser (e2e):** no SaaS call is ever made (D24), and a Slack, Teams or Google Chat connection can't point at a
  local sink (each must match its service's webhook host, e.g. `SLACK_URL`). So the e2e covers the drawer without
  publishing: a draft with a message step (no connection), the composer, the preview and the states, with axe, light
  and dark, at 1280 and 320 px.

## 7. Risks

- **The mirror drifts from a renderer.** The shared cases fail the backend test when a renderer changes; a change the
  cases don't exercise can still drift. The previews say "Laid out as Slack shows it", never "exactly".
- **JSON's bytes in TypeScript and Python** differ on rare characters (lone surrogates; control characters' escapes).
  Teams' and Google Chat's budgets are counted on the encoded body: the cases include multi-byte and control text; a
  remaining difference shifts a warning by a few bytes, never what's sent.
- **The multi-line editor** is new: line rows of the existing pill editor, without `contenteditable`. Caret moves
  between lines (Up, Down, Home, End) need their own handling and tests.
- **Third-party message plugins** get the composer without a preview: right, since no mirror of their renderer exists.

## 8. Calls I made, for the owner to check

1. **The hint is `x-widget: "message"` at the root of the SDK's `Message`,** so every config built on it gets the
   composer; not a hint per field.
2. **Which preview a step gets** comes from its plugin (Slack, Teams, Google Chat, the webhook's `send_message`): the
   mirrors are of those renderers, so a third-party message step gets the composer without a preview.
3. **The shared cases live in the frontend's test support,** written by a backend command and checked by a backend
   test and a frontend test.
4. **The text's lines are rows of today's pill editor:** Enter splits, Backspace joins; no `contenteditable`.
5. **The Slack count** is the escaped text's length before its values, as Slack's renderer counts; Teams and Google
   Chat say bytes against their budget.
6. **A link's address is checked only when it starts with written text.**
7. **One plan,** the backend's two tasks first (the hint, the shared cases), then the UI; no backend plan of its own.
8. **The Test tab's message result in words** (§5.6) is in 4f-1, as the States board draws it, without the board's
   "(3,214 with its values)", which the step's output can't give.
9. **A long run of written text is split at the engine's 4,096 characters when saved,** in the shared writer, so a
   text with values can reach the model's 40,000 characters.
10. **Rows keep Move up and Move down;** no Edit as JSON on the message's lists.
11. **Labels take values too,** as values and addresses do (§3, answer 8).
12. **A formula part shows "Computed when the step runs" in the preview** and is left out of the cut maths.
