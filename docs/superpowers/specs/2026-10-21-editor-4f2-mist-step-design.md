# Editor UI 4f-2: the Mist step — design

**Status:** written 2026-10-21 for the owner's review. D8 signed off on the Design canvas "4f-2 Mist Step Mockups",
version 7 (https://claude.ai/artifact/RvfFyvE8GoNAnLV3kRRkJ2): boards Main, Picker, FindSetting, CreateDevice, States,
MainDark, MoreStates, Narrow320Light, Narrow320Dark. §3 corrects some of the boards' words after facts found later.

**Sub-project 4 (editor UI), slice 4f** (outline `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md` §2, 4f):
"the Mist picker (Resource → Action, live options that accept pills, Find a setting), nested update, …". 4f is split
in three (4f-1 spec §2); this is the second.

Research: `~/4_dev/mist_dewpoint-4f-notes` R4 (the Mist step measured) and R5 (facts for this spec, file:line at
5882c682).

## 1. What 4f-2 is

The Mist plugin has 294 steps over 85 resources (`mist.<resource>.<action>@1`). Today:

- the add-step picker lists them as 294 rows among the other actions, searched by title and ref;
- a path id with choices (`site_id`, an org resource's id: 28 fields) is typed, or picked by its UUID from a select,
  and takes no value from an earlier step (ledger ruling 127);
- an update's body draws every field it has at once (about 676 for site settings, 267 for a WLAN), its `mode` a select
  and its `clear` a list of raw names;
- a device's body (`site_devices.update`, the device profiles) holds a sensitive part, so it can only be a formula;
- every body setting is labelled by its raw name (`min_rogue_rssi`).

4f-2 gives:
- the picker, Mist as its resources, then a resource's actions;
- path ids that take values from earlier steps and still show choices;
- an update's body as **Changes**: only the settings it changes, each Set or Clear, found by name or description;
- a create's body as **Settings**: the required ones first, the others added;
- a device's kind first, then that kind's settings;
- labels in words, from the plugin, the raw name beside.

Not in 4f-2:
- a merged-body preview (plugins-3 ruling L4: it needs a read of Mist; with 4d-2);
- choices for a site's resources (a device id: plugins-3 3b-2 ruling) or beyond the route's 1,000;
- the generic `mist.api.read/write` steps and the 32 action bodies (utilities' and others'): the generic form, as today;
- changing a step's type in the drawer (§2, answer 2);
- grouping other plugins' steps in the picker (the board's "Messaging" heading): they stay under "Actions".

## 2. The owner's answers (2026-10-21)

1. **"Start 4f-2":** research first, then propose (R4), as for 4f-1.
2. **The chooser is the add-step picker only:** no change of type inside the drawer.
3. **A create's body is the same list, Set only,** the required settings first.
4. **Labels are words from the plugin,** display titles outside the contract hash, the raw name beside in the code face.
5. **A device's body: choose the kind, then its settings** (AP, switch or gateway).
6. **Round 1 approved** ("looks good"), with the five calls drawn: Changes on Setup (amending ruling 98); a Set |
   Clear choice per setting and Keep to take it off the list; a picked choice's name shown until the drawer closes; a
   change of kind keeps the changes the new kind has and names the ones it drops; the picker shows Mist as resources.
7. **D8 signed off** at version 7 ("signed off, write the spec").

## 3. Corrections to the boards

Found in the code after sign-off (R5 §3, §6); the words below replace the boards' where they differ.

1. **Replace doesn't reset the other settings.** Both modes send a PUT, and Mist's PUT merges at the top level
   (`plugins/mist/nodes.py:8-10, 208-219`): a setting not listed stays as it is in either mode. The modes differ only
   inside a setting that is an object: merge reads the current one when the step runs and keeps the parts not given;
   replace sends the setting as written, so its parts not given go back to Mist's defaults. The States board's "Mist
   resets the site's other 99 settings to their defaults" is wrong; §5.5 has the words.
2. **Read-only settings aren't offered.** The schemas mark Mist's server-set settings `readOnly` (`id`, `org_id`,
   `created_time`…: 9 of site settings' 102, 11 of a WLAN's 106). The lists leave them out, so the counts are 93 and
   95, not 102 and 106.
3. **Nothing in a schema names the object** ("the site's", "the device's", "a WLAN's"), so the words don't: "Merge
   with the current settings", "3 of 93 settings change".
4. **A resource's label carries its scope** ("Site settings", "Org WLANs", "Site devices", "Org alarms"), as Mist's own
   names do, so the picker's rows say "5 actions" without "org ·" or "site ·". It also tells `org_devices` from
   `site_devices`, which the board's "Devices" wouldn't.
5. **The drawer's third line is "Mist · Site settings",** the group, without "· Update" (the title already says it).
6. **The device id's sentence** ("A device has no choices to show: it belongs to a site.") isn't shown: nothing in the
   schema says why a field has no choices. Its hint is its description, as today.
7. **A setting of several shapes** says "As JSON: Mist takes it in more than one shape.", not a sentence per setting.

## 4. Backend: display metadata from the Mist plugin

All of it is display metadata the contract hash drops (`engine/registry/catalog.py:31-32`: node `title`,
`description`, `icon`; in schemas `title`, `description`, `examples`, `x-widget`, `x-group`, root and `$defs`
included). The registry refreshes a version's manifest in place when its hash is equal
(`core/plugins/registry.py:99-101`). No new version, no engine, API or client change; the 4f-1 precedent is
`x-widget: "message"` (4f-1 spec §4.1).

### 4.1 The step's group: `x-group` at the config's root

Each of the 294 Mist configs carries at its root `"x-group": {"plugin": "Mist", "title": "<resource label>"}`.

- A new node-level key would be hashed and isn't served (`GET /node-types` builds its rows key by key into a model that
  forbids extra keys, `apps/api/routes/node_types.py:88-111`); the config root is the one hash-free place a plugin
  can put it (R5 §1-2).
- `title` is the resource's label: the existing `title()` (`plugins/mist/titles.py:53-69`) of the resource name
  (`site_settings` → "Site settings", `org_wlan_templates` → "Org WLAN templates", `site_devices` → "Site devices"),
  with written overrides where it reads wrong (`const_webhook_topics` → "Webhook topics", `api` → "API", `site` →
  "Site", `org` → "Org"). The 85 labels are distinct.
- `plugin` is the heading the picker shows over the plugin's groups ("Mist").
- At a field, `x-group` stays unused (ruling 98 holds: fields are ordered by the schema).

### 4.2 Setting titles

Every property entry of every create, update and action body, at every depth, gets a `title`: the property's name in
words.

- On the property's own entry, beside a `$ref`, never on a shared `$defs` component: `$defs/wlan_limit` serves four
  settings, `$defs/id` many (R5 §5; the drawer lets an entry's own keys win, `lib/schemaForm.ts:62`).
- The words: `title()`'s rule with a second table of body terms (SSID, VLAN, ACL, IP, IPv6, SNMP, NTP, MTU, LLDP, STP,
  PoE, VRF, RADIUS…): `vlan_id` → "VLAN ID", `acl_tags` → "ACL tags", `min_rogue_rssi` → "Min rogue RSSI",
  `allow_mist` → "Allow Mist". The second table doesn't feed node or path titles, which stay as signed off (`radius` and
  `dot1x` stay lower case there, plugins-3 ledger 1922); its own test requires each term to be reached by some body
  property name.
- A union's alternatives get titles: each device alternative its kind ("AP", "Switch", "Gateway", from the one value of
  its `type` enum); the unions themselves "Device" (`mist_device`) and "Device profile" (`deviceprofile`).
- About 10,500 entries, some 240 KB more in the catalogue served to the editor (7.8 MB today, 1.4 MB gzipped).

### 4.3 The widget hints

- The 40 updates (each has `body`, `mode`, `clear`) carry `"x-widget": "update"` at their config's root; the 36
  creates (a required `body`) carry `"x-widget": "create"`.
- The hints name built-in widgets (arch §101): a third-party plugin with the same contract gets them too. A config
  with the hint but without the parts the widget needs (`body`; for an update, `mode` with `merge` and `replace`, and
  `clear` an array of names) falls back to the generic form, as 4f-1's does without `text`.
- Ruling 100's example name `nested-update` isn't emitted anywhere; the shorter name costs nothing.

### 4.4 Nothing else changes

- No route, migration, ABI change or new step version.
- Values from earlier steps already pass validate and publish in a path id: a template is checked by type only, and the
  uuid pattern binds literals (`engine/graph/validate.py:996-1031`). The pattern is checked when the step runs
  (`config_invalid`, `mist.invalid_path_value`), as for a typed id today. Amending ruling 127 needs nothing here.
- `mist.nothing_to_change` and `mist.conflicting_change` stay run-time refusals; the drawer says them before (§5.9).
- A test pins the 294 contract hashes as they are at 5882c682.

## 5. The UI, per the signed-off boards and §3

### 5.1 The add-step picker (Picker, MoreStates)

Opened as today (`A` on the canvas, "＋ Add step", a "+"); ⌘K stays the global palette.

- **Nothing typed:** "Flow" as today; then, for each plugin whose steps carry `x-group`, a heading from its `plugin`
  ("Mist: 85 resources, type to find one") over one row per group, by label: the label, "N actions" in the code face,
  and the actions' words ("List, Get, Create, Update, Delete"; "Get, List, Restart, Ping, Bounce port…", cut after 6).
  The steps without `x-group` stay under "Actions", as today.
- **Typing:** a group is listed when each typed word is in its label or its resource name. A grouped step is listed
  itself, above the groups, when its title starts with what's typed or its ref holds it ("update org wlan" →
  Update org WLAN). Steps without `x-group` keep today's search.
- **A group chosen** (Enter or a click): its actions, in a view headed "← Back · Mist · **Org WLANs**", by title. Each
  row: the title, the ref in the code face, and today's words ("Changes things; safe to repeat."), with the
  connection's type named by its label from `GET /api/v1/connection-types` ("Uses a Mist connection"), not its key
  (today's "Uses a mist connection"). Back, or Backspace in the empty search, returns.
- Inserting on an edge offers only steps with a continuation port, as today; a group with none isn't listed.
- The search box's name says what it finds: "Type a step's name or a Mist resource".

### 5.2 Path ids: values and choices (Main, States)

A path id with choices (`x-dewpoint-options`, 28 fields) gets today's "Text" mode with pills (ruling 127 amended:
live options take pills) plus "Show choices":

- The field holds written text, values from earlier steps, or both, as any text field with pills. "＋ Data" and / work
  as elsewhere. Formula stays offered.
- **Show choices** loads them on request as today (ruling 109 holds: never on render; one scope per era; the words of
  each failure). The query is the field's written text when it holds no value from a step, else empty.
- The choices show as a list under the field (ruling 126: in the drawer's flow, no popover), not today's select: each
  row the choice's name and the start of its id in the code face; Up, Down, Enter, Escape; "N choices"; it scrolls past
  ten.
- **A pick** replaces the field's content with the choice's value, and the field says "HQ Paris, picked from the
  choices." until the drawer closes or the value changes. The name isn't saved (the config holds the id); a reopened
  drawer shows the id.
- The hint: "A value from an earlier step, or one of the connection's choices: Show choices lists them."
- A path id without choices (a device's id) is today's text with pills, its description as its hint.

### 5.3 Changes: an update's body (Main, States)

A step whose config root has `x-widget: "update"` draws `body`, `mode` and `clear` as one fieldset, **Changes**, on
Setup after the path ids (ruling 98 amended for it: Setup holds the changes, optional or not).

- **How they're sent:** a radio pair, "Merge with the current settings" (the default, as `mode`'s) and "Replace them",
  with the words of §5.5.
- **Find a setting** (§5.4), then one row per setting that changes, then "＋ Add a setting", then the count: "3 of 93
  settings change; the others stay as they are." (the settings sent or cleared, of those the list offers).
- **A row:** the setting's title, its raw name under it in the code face, and at its right a Set | Clear choice and
  "Keep" ("Keep Rogue as it is").
  - **Set** puts the setting in `body`; its control follows (below).
  - **Clear** puts its name in `clear`: "Sent empty: Mist removes this setting." A value set before is kept in the drawer
    until it closes, so Set brings it back.
  - **Keep** takes the row off: the setting leaves `body` and `clear`. Keep is what every unlisted setting does.
- **Rows are ordered by title.** Stored JSON doesn't keep key order (`jsonb`), so neither does the list; a new row
  takes its place and scrolls into view.
- **A Set setting's control** is today's control for its type: text with pills, a number, a choice, JSON for a union
  (§5.8), the sensitive control for an `x-sensitive` part (ruling 101).
- **An object shows only the parts given,** each labelled by its title, and "＋ Another setting of Rogue", which opens
  Find a setting over that object's own settings. This holds for every object at any depth, to ruling 100's bound (8
  levels; a repeated `$ref` is JSON), a map's entry and a list's item included:
  - a **map** (an open object: `port_usages`, a gateway's `port_config`) lists its entries by key ("Port usages ›
    trunk"), each an object showing its given parts, with "＋ Add an entry" (its key first);
  - a **list** of objects (`networks`) lists its items by number ("Networks › item 2"), each showing its given parts,
    with "＋ Add an item" and today's Move up and Move down;
  - a list or map of plain values (SSIDs, VLAN ids) is today's control.
  Without this, one gateway port draws 48 fields at once.
- **A part inside a Set setting is taken off with "Remove"** ("Remove Min RSSI"): it isn't sent, so with merge it
  stays as it is in Mist. Today's per-field "Clear" isn't shown inside a row: Clear means "Mist removes this", and
  only a top-level setting can be cleared (plugins-3 ruling: `clear` names top-level fields).
- **A setting given nothing isn't sent.** An emptied value leaves the body (ruling 102); a Set row with nothing given
  says "Nothing given yet: it isn't sent." and is gone when the drawer reopens. So an empty object is never sent (which,
  with replace, would reset it).
- **Read-only settings** (`readOnly: true`, at any depth) are never offered: not in Find, not as a row, not to clear.
  A required one is the exception (§5.6).
- **A union alternative's kind setting** (§5.7) is never offered either.

### 5.4 Find a setting, Add a setting (FindSetting, MoreStates)

- One search box over the step's settings, top-level and nested (not read-only): "Find a setting by its name or what it
  does". A combobox: the list opens under it, Up and Down move, Enter adds, Escape closes.
- **A match:** every typed word, case-insensitive, is in the setting's title, raw name or description, or in the titles
  on its path. Ranked: a match in a title or name before one only in a description, top-level before nested, then by
  title. Each hit shows its path of titles ("Rogue › Min rogue RSSI"; through a map "Port usages › an entry › Mode",
  through a list "Networks › an item › VLAN ID"), its raw path in the code face, and its description on one line;
  matched words are bold and underlined, not coloured. At most 50 shown: "50 of 212 shown: type more to narrow."
- **What it searches:** site settings has 656 settings through its objects and 1,746 through its maps and lists too; a
  gateway template 97 and 568. The index is built once per type.
- **Adding a top-level setting** adds its row, Set, and moves focus to its control; an object opens its own settings'
  list ("＋ Another setting of …" opened).
- **Adding a nested setting** adds its top-level setting (if absent) Set, with the path down to it given, and moves
  focus to its control. Through a map, a new entry is opened with its key to type first; through a list, a new item.
  An existing entry or item takes the setting from its own "＋ Another setting of …".
- **A setting already listed** says "· In Changes"; Enter goes to its row (and, for a nested one, opens it there).
- **Nothing matches:** 'No setting matches "firewall", by name or description.'
- **＋ Add a setting** focuses the box with nothing typed: the top-level settings, by title ("93 settings; the list
  scrolls."). Nested ones show once something is typed.

### 5.5 What each mode sends: the words (Main, States)

- **Merge** (under the choice): "Merge reads the current settings when the step runs and keeps the parts of each
  setting below that you don't give. A change made in Mist in between may be overwritten."
- **Replace** (warn ink, never an error): "Replace sends each setting below as written: the parts you don't give go back
  to Mist's defaults. Settings not listed stay as they are."
- **Under a Set object or map,** by mode: "Its parts left empty stay as they are: merge changes only those given." /
  "Its parts left empty go back to Mist's defaults: replace sends it as written." (Merge fills a map entry by entry, as
  an object: `nodes.py:70-74`.)
- **Under a Set list of objects,** in either mode: "A list is sent whole: it replaces the current one, and an item's
  parts left empty go back to Mist's defaults."
- A list of plain values, a number or text is sent whole in either mode; it says nothing more.

### 5.6 Settings: a create's body (CreateDevice)

A step whose config root has `x-widget: "create"` draws `body` as **Settings** on Setup, the same list without Keep or
Clear:

- the body's required settings first, in the schema's order, never removable ("SSID (required)"); the others by title,
  each with "Remove" ("Remove Enabled");
- Find a setting and "＋ Add a setting" as §5.4; the count "3 of 95 settings given; Mist uses its defaults for the
  others.";
- a required setting left empty says "Required" (ruling 102);
- a required setting whose schema allows one value (a device profile's `type`) is filled with it and shown read only.

### 5.7 A device's kind (CreateDevice, MoreStates)

A body that is a union of objects (`anyOf` or `oneOf`) with titled alternatives shows, first in Changes or Settings,
"Kind of device" (the union's title, its first letter in lower case): a radio group of the alternatives' titles, "AP",
"Switch", "Gateway".

- The settings offered (Find, Add, rows) are the chosen kind's; "Its settings are the AP's."
- **Changing the kind** keeps the rows the new kind also has and drops the others, saying which: "Kind changed to
  Switch: Name and Notes are kept; LED and Height are dropped, as a Switch doesn't have them." (a status message).
- **The kind's setting** is a property that, in each alternative, allows one value (`type`: "ap", "switch",
  "gateway"). It's never offered as a setting (not in Find, not as a row, not to clear); the kind writes it.
- **Where the kind is kept:**
  - a create writes it, required (§5.6; a switch profile's `type` is required and read only: required wins);
  - an update writes it only when the draft already holds it, and then rewrites it with the kind. Otherwise it isn't
    sent: `site_devices.update` marks it read only for every kind, and a profile's kind is Mist's already;
  - a reopened drawer reads the kind from that setting when the draft holds it, else from the rows: the first kind (in
    the union's order) that has every setting listed; with none listed, or only shared ones, the first (AP). Changing
    it then loses nothing.
- No fixed value could be given for these bodies before (a sensitive part made them formula only); the list gives
  them one, each sensitive part with its own control (ruling 101).

### 5.8 What the list can't draw (States)

- **A setting of several shapes** (a union: six of a WLAN's, `vlan_id` among them) is Set as JSON in its row: "As
  JSON: Mist takes it in more than one shape."
- **The whole body from a formula:** Changes (or Settings) has the switch "List | Formula" beside its legend (ruling
  101's switch, "List" naming the fixed side). Formula is today's formula field, with "Computed when the step runs: the
  settings it gives are set; with merge, the parts it leaves out stay as they are." (a create: "…are sent; Mist uses its
  defaults for the others."). Cleared settings stay listed as Clear rows, and "＋ Add a setting" adds one to clear.
- **A draft from elsewhere** (the API, Edit as JSON): a part the widget can't draw (a `mode` or `clear` held as a formula
  or a reference; a `clear` naming a setting the list doesn't offer) shows today's control for that part, unchanged:
  opening the drawer never rewrites a draft (ruling 102). A setting both set and cleared shows one row, "Both set and
  cleared: Mist refuses this when it runs. Choose Set or Clear.", and the step can still be saved.

### 5.9 Options, nothing to change, read only (States, MoreStates)

- **Options:** "The changes are on Setup." (a create: "The settings are on Setup."), then the step's other optional
  fields, or "Nothing else to set." as today.
- **Nothing to change:** with no row sent or cleared and the body not a formula, Changes says "Nothing to change yet:
  add a setting to set, or one to clear. An update that changes nothing fails when it runs." A warning, never an
  error: the step publishes (the refusal is the run's, `mist.nothing_to_change`).
- **A value past a limit** is said under it, as for any field today ("At least -85.": the schema's own bounds,
  ruling 102).
- **Read only** (a version viewed, a role that can't edit): no controls. "Merge with the current settings · 3 changes",
  then one line per row: "Auto upgrade: set: Enabled yes, Version <pill>, Time of day 02:00, Day of week sun";
  "Remote syslog: cleared". A nested object one level down shows its count ("Marvis: set: Auto operations, 1
  setting"); a sensitive part "a sensitive value", never its content.

### 5.10 The drawer's header and labels

- Header: the step's key; "Update site settings · mist.site_settings.update@1"; "Mist · Site settings" from `x-group`.
- A setting's title labels it; the raw name shows beside it in the code face only on a row of Changes or Settings and
  in Find's hits (the boards), not on its parts or any other field. A setting without a title (another plugin's) is
  labelled by its name, as today. The generic form gains nothing new: the action bodies' new titles label their fields
  as any title does.

### 5.11 Accessibility, 320 px (Narrow320Light, Narrow320Dark, MainDark)

- WCAG 2.2 AA, light and dark, at 1280 and 320 px; targets at least 24 px, 44 px at 320 (in px, since a rem is 14 px
  here: 4f-1's lesson).
- Changes and Settings are fieldsets with their legend; "How they're sent" and "Kind of device" radio groups; Set |
  Clear a group named by its setting ("What happens to Rogue") of two pressed buttons; Find a setting a combobox with
  `aria-activedescendant`; the choices a listbox; the kind's change and "In Changes" status messages; errors and
  warnings linked to their control.
- At 320 px: the merge and replace choices stack; a row's Set | Clear and Keep go under its title; an object's parts
  stack, label above value; the picker is full width, each action's ref under its title.
- No AI tells (`src/test/aiTells.test.ts`).

## 6. Testing

- **Backend:** every Mist config root has `x-group` with `plugin` "Mist" and one of 85 distinct titles; the 40
  updates have `x-widget: "update"`, the 36 creates `"create"`; every body property entry at every depth has a title,
  with pinned examples (`ssid` "SSID", `vlan_id` "VLAN ID", `min_rogue_rssi` "Min rogue RSSI", `acl_tags` "ACL tags",
  `auto_upgrade` "Auto upgrade"); the device alternatives and unions are titled; no shared `$defs` component gains a
  title other than a union alternative's; node and path titles unchanged; the 294 contract hashes unchanged (a pinned
  file).
- **Frontend, unit:** fixture node types are made up (D24: an `acme.*` update with a `$defs` body, titles, read-only
  settings, nested objects, a list, a union setting, a sensitive part; a create with a required setting; a root union
  with titled alternatives; `x-group` on several), never Mist's own. The picker's groups, search and Back; pills and
  choices in a path id, the pick's name; Changes' rows (Set, Clear, Keep, ordering, nothing given, the count); Find
  (matching, ranking, the cap, nested adds, In Changes, nothing matches); the mode words; Settings; the kind (keeping,
  dropping, reading it back); JSON rows; the body formula; drafts from elsewhere; Options; nothing to change; read
  only; 320 px.
- **Browser (e2e):** no Mist call is ever made (D24). As 4f-1 placed a real Slack step without a connection, a real
  `mist.site_settings.update@1` step is placed without one: the picker by resource, Changes, Find a setting, the
  modes' words, read only; axe, light and dark, 1280 and 320 px. Show choices stays disabled (no connection).

## 7. Risks

- **Titles by rule** will read badly for some of the 1,325 names (`dot11r`). They're display metadata: fixed later
  without a version.
- **The kind of an update isn't saved:** a reopened drawer guesses it from the rows (§5.7); a wrong guess costs a click
  and loses nothing.
- **The modes' words rest on Mist's PUT merging at the top level,** as the plugin's own code says (`nodes.py:8-10`). If
  Mist differs for some resource, the words are wrong there; no Mist call is made to check (D24).
- **`x-group` at a config's root** is a new use of a name ruling 98 had kept for field groups; a later field grouping
  reads it per field, where it stays unused.
- **Find over descriptions** runs in the browser on each keystroke over up to 1,746 settings (site settings, through
  maps and lists): an index built once per type keeps it cheap.
- **Maps and lists in the given-parts model** (§5.3) make 4f-2b the larger plan: entries, items and their adds are new
  controls, not today's.

## 8. Calls I made, for the owner to check

1. **The resource label goes in `x-group` at the config's root,** `{"plugin", "title"}`: the only hash-free place a
   plugin has (§4.1).
2. **Labels carry their scope** ("Site devices", "Org alarms"), from `title()` of the resource name with a few written
   ones; rows say "N actions" (§3.4).
3. **Setting titles by rule** (`title()` plus a body-terms table), on each property entry; device kinds titled by their
   `type` value.
4. **Hints `x-widget: "update"` and `"create"`** at the root of the 40 updates and 36 creates; the action bodies keep the
   generic form.
5. **The corrected words** of §3 and §5.5 (replace, read-only counts, no object nouns).
6. **Read-only settings are left out** of Find, the rows and Clear.
7. **Rows ordered by title,** since stored JSON keeps no key order.
8. **A Set setting given nothing isn't sent,** objects included (an empty object, with replace, would reset it).
9. **An object row shows only its given parts,** with "＋ Another setting of …".
10. **Find:** every word must match; titles and names rank above descriptions; at most 50 shown.
11. **A grouped step is listed by itself** when its title starts with what's typed or its ref holds it; a group's actions
    are ordered by title.
12. **Choices as a list under the field,** not today's select; the pick's name not saved.
13. **An update's device kind isn't saved,** it's read back from the rows; a create's goes in its required `type`.
14. **"Uses a Mist connection"** names the connection's type by its label, in every action row.
15. **Two plans:** 4f-2a, the plugin's metadata, the picker and the path ids; 4f-2b, Changes, Settings and the kind.
    Each ships on its own; the backend task opens 4f-2a.

From the builder check:

16. **The given-parts model goes through maps and lists of objects** (a map's entries by key, a list's items by
    number), and Find reaches into them; lists and maps of plain values keep today's control. Merge treats a map like
    an object and replaces a list whole, and the words say so (§5.5).
17. **A part inside a row is taken off with "Remove",** never "Clear": only a top-level setting can be cleared.
18. **The kind's setting** (`type`) is never offered; written by a create, rewritten by an update only when the draft
    holds it, and read back from it when present (a profile update's AP and gateway `type` aren't read only).
19. **The raw name shows only on rows and in Find's hits,** not on their parts or any other field.
