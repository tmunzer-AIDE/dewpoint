# Node types and CEL profiles: registration and lifecycle

Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §4.5.

## Register on every deploy

Run `plugins sync` with the `dewpoint_admin` database credentials, before the new API or worker build serves traffic:

```bash
DEWPOINT_DATABASE_URL=postgresql+asyncpg://dewpoint_admin_login:...@postgres/dewpoint dewpoint plugins sync
```

It registers every node type version the build contains, the connection types its plugins declare (the API knows a
connection type, `mist` included, only once a sync registered it: until then, creating one is refused as
`unknown_type`), the triggers they declare (`GET /api/v1/trigger-types` lists them: the Mist webhook trigger's 30 topic
schemas), and this build's CEL profile. Mist's plugin declares 294 node types (one per curated operation of its policy
map, one per reviewed device utility, and `mist.api.read` and `mist.api.write`), so its first sync checks an 8 MB
manifest: about 12 seconds. It
refuses to proceed (exit 2) when:

- **a registered version's contract changed.** Anything other than its title, description, icon or schema annotations (`title`, `description`, `examples`, `x-widget`, `x-group`) differs from what was registered: schemas, ports, kind, side effect, credentials, capabilities, retry policy or timeout. Ship the change as a new version (`type@N+1`) with a config migration. Display-only changes are stored in place.
- **the build lacks a node type that isn't retired.** Published versions may still need it. Retire it first (below).

## Deprecate, migrate, retire

1. `dewpoint lifecycle deprecate --node-type mist.object.update@1`
   - New versions can no longer use it; the editor offers the migration.
   - Everything already active keeps running.
2. Tenants republish their workflows on the newer version.
3. `dewpoint lifecycle retire --node-type mist.object.update@1`
   - **Succeeds (exit 0)** when no enabled workflow's active version uses it, directly or through a pinned sub-flow.
   - **Refuses (exit 4)** otherwise, and lists the workflows that still use it.
4. **Forced retirement.** Only when you accept that those workflows stop being startable.
   - `... retire --node-type X --force` prints the preview and changes nothing (exit 3).
   - `... retire --node-type X --force --confirm` applies it.
   - Each affected tenant gets an audit entry, and the workflows show `executable: false` with `blocked_by`.
5. Re-enabling a disabled workflow re-checks its active version the same way activation does. If anything it uses is retired, the request is refused (`not_enableable`). Normal retirement doesn't count disabled workflows, so this check is what stops them coming back.
6. After retirement, a later build may drop the code.
   - Runs already in progress are unaffected: they stay on the worker build they started on, which still has the code, until Temporal reports that build drained. (The engine plan 2a-3 covers this.)

CEL profiles follow the same commands with `--cel-profile <profile>`. A profile's evaluator must keep running until no
run that is still in progress uses the profile.

## Why the locks matter

Publishing, activation and (from sub-project 2b) run admission take a shared lock on every node type and CEL profile
their version uses, then re-check its state. Retirement takes the exclusive lock first. Either retirement sees the new
reference, or the new reference sees the retirement; a request is never admitted against code that is being removed.
