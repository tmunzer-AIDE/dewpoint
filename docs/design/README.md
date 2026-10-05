# Design references

`2026-10-05-dewpoint-ui.dc.html` is the Claude Design export that sub-project 4 (the editor UI) implements: screens
1a–1i, and today's UI as 0a–0b. It's committed byte for byte so the outline's line references
(`docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md` §7) can be checked.

- It is design data, never application content. The web image copies only `frontend/`.
- The design tool's `support.js` isn't committed, so the file doesn't render on its own: read it as markup.
- Its names, IDs, addresses and figures are fictional. It links Google Fonts. The app bundles its fonts instead, under
  a CSP that forbids remote origins.
- Where it differs from the shipped UI, the outline's rulings win (§3, and §6's rule against AI design tells).
