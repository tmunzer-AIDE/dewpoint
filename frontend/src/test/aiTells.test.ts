// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { findTells } from "./aiTells";

const TOKENS = "/src/styles/tokens.css";

describe("findTells", () => {
  it.each([
    ["accent-border", "a.tsx", `<div className="border-l-4 border-accent">`],
    ["accent-border", "a.tsx", `<div className="border-t-[3px]">`],
    ["accent-border", "a.css", `.callout { border-left: 3px solid var(--live); }`],
    ["gradient", "a.tsx", `<div className="bg-gradient-to-r">`],
    ["gradient", "a.css", `.x { background: linear-gradient(red, blue); }`],
    ["gradient", "a.tsx", `<div className="bg-linear-to-r from-accent to-live">`],
    ["gradient", "a.tsx", `<div className="bg-radial from-accent">`],
    ["gradient", "a.tsx", `<div className="bg-conic-180">`],
    ["accent-border", "a.tsx", `<div className="border-s-4 border-accent">`],
    ["accent-border", "a.tsx", `<div className="border-e-[3px]">`],
    ["halo", "a.tsx", `<div className="shadow-[0_0_0_4px_var(--accent-soft)]">`],
    ["heavy-shadow", "a.tsx", `<div className="shadow-accent">`],
    ["heavy-shadow", "a.tsx", `<div className="shadow-sm">`],
    ["heavy-shadow", "a.tsx", `<p className="text-shadow-lg">`],
    ["decorative-motion", "a.tsx", `<div className="transition duration-300">`],
    ["decorative-motion", "a.tsx", `<span className="animate-[spin_2s]">`],
    ["blur", "a.tsx", `<div className="backdrop-blur-md">`],
    ["blur", "a.css", `.x { backdrop-filter: blur(8px); }`],
    ["halo", "a.tsx", `<div className="ring-4 ring-accent-soft">`],
    ["halo", "a.css", `.node { box-shadow: 0 0 0 4px var(--accent-soft); }`],
    ["heavy-shadow", "a.tsx", `<div className="shadow-xl">`],
    ["decorative-motion", "a.tsx", `<span className="animate-pulse">`],
    ["decorative-motion", "a.css", `.skeleton { animation: shimmer 1s; }`],
    ["emoji", "a.tsx", `<span>Done ✨</span>`],
    ["emoji", "a.tsx", `<span>Ship it 🚀</span>`],
    ["eyebrow", "a.tsx", `<p className="uppercase">Trigger</p>`],
    ["eyebrow", "a.tsx", `<p className="tracking-widest">TRIGGER</p>`],
    ["eyebrow", "a.tsx", `<p className="tracking-[0.12em]">TRIGGER</p>`],
    ["large-radius", "a.tsx", `<div className="rounded-2xl">`],
    ["large-radius", "a.css", `.card { border-radius: 16px; }`],
    ["raw-colour", "a.tsx", `<div style={{ color: "#0b7c8c" }}>`],
    ["raw-colour", "a.css", `.x { color: rgba(0, 0, 0, 0.5); }`],
    ["raw-colour", "a.tsx", `<div className="bg-indigo-500 text-white">`],
    ["marketing-copy", "a.tsx", `<p>Seamlessly automate your network!</p>`],
    ["marketing-copy", "a.tsx", `<p>Oops, something broke</p>`],
    ["accent-text", "a.tsx", `<button className="text-sm text-accent underline">`],
    ["hatch-text", "a.tsx", `<div className="hatch-sim rounded-lg bg-surface">`],
    ["type-scale", "a.tsx", `<h1 className="text-2xl font-semibold">`],
    ["type-scale", "a.tsx", `<td className="p-3 font-mono text-[13px]">`],
    // What the checkpoint review found the guard missing (Tailwind 4.3.3 generates each).
    ["heavy-shadow", "a.tsx", `<div className="shadow rounded-lg">`],
    ["blur", "a.tsx", `<img className="blur" />`],
    ["decorative-motion", "a.tsx", `<div className="transition duration-[400ms]">`],
    ["decorative-motion", "a.tsx", `<div className="transition duration-175">`],
    ["accent-border", "a.tsx", `<div className="border-r-4 border-accent">`],
    ["accent-border", "a.tsx", `<div className="border-x-4 border-accent">`],
    ["gradient", "a.tsx", `<div className="mask-b-from-50%">`],
    ["gradient", "a.tsx", `<div className="mask-radial-from-40%">`],
    ["halo", "a.tsx", `<div className="outline-4 outline-accent-soft">`],
    ["heavy-shadow", "a.css", `.card { box-shadow: 0 12px 32px var(--line); }`],
    ["heavy-shadow", "a.css", `.row { box-shadow: inset 3px 0 0 var(--accent); }`],
    ["accent-border", "a.css", `.callout { border-right: 3px solid var(--live); }`],
    ["accent-border", "a.css", `.callout { border-left: solid 3px var(--live); }`],
    ["decorative-motion", "a.css", `.x { transition: opacity 400ms ease; }`],
    ["decorative-motion", "a.css", `.x { animation: spin 2s linear infinite; }`],
    ["decorative-motion", "a.css", `@keyframes float { to { transform: translateY(-4px); } }`],
  ])("flags %s in %s", (rule, path, text) => {
    expect(findTells(path, text)).toContain(rule);
  });

  it.each([
    ["a separator and a tab underline", "a.tsx", `<div className="border-l border-b-2 border-line">`],
    ["a focus ring", "a.tsx", `<button className="ring-2 ring-offset-2">`],
    ["the 8 px radius and a token radius", "a.tsx", `<div className="rounded-lg rounded-dialog">`],
    ["a loading spinner", "a.tsx", `<span className="animate-spin">`],
    ["the UI's glyphs", "a.tsx", `<kbd>⌘K</kbd> → ▾ ✓ ◌ ＋`],
    ["a heading's tight tracking", "a.tsx", `<h1 className="tracking-tight">`],
    ["colours in the token sheet", TOKENS, `:root { --ink: #15181c; --rail-active: rgba(255, 255, 255, 0.1); }`],
    ["a token shadow", "a.css", `.node { box-shadow: var(--shadow-node); }`],
    ["the token shadows and quick motion", "a.tsx", `<div className="shadow-node shadow-dialog duration-150 duration-100">`],
    ["accent ink as text, accent as a fill", "a.tsx", `<a className="text-accent-ink bg-accent text-on-accent">`],
    ["the hatch behind slate text", "a.tsx", `<span className="hatch-sim bg-sim-bg text-sim">Simulated</span>`],
    ["the type tokens", "a.tsx", `<p className="text-small text-body-lg text-h1 text-caption">`],
    ["the hatch's own stylesheet", "a.css", `@import "./tokens.css";\n.hatch-sim { position: relative; }\n.x { content: ""; }`],
    ["a quick transition", "a.css", `.x { transition: background-color 150ms; }`],
    ["the hatch's mask", "a.css", `.hatch-sim::before { mask-image: url("./hatch.svg"); mask-size: 6px 6px; }`],
    ["a 2 px outline in the focus colour", "a.tsx", `<li className="outline-2 -outline-offset-2 outline-focus">`],
    ["no shadow, and the word in prose", "a.tsx", `// The dialog's shadow is a token.\n<div className="shadow-none">`],
  ])("passes %s", (_, path, text) => {
    expect(findTells(path, text)).toEqual([]);
  });

  it("lets a file opt out of one rule, by name", () => {
    const wordmark = `// ai-tells-allow: eyebrow (the wordmark, outline §6)\n<span className="tracking-[0.12em]">FOR JUNIPER MIST</span>`;
    expect(findTells("Wordmark.tsx", wordmark)).toEqual([]);
    expect(findTells("Wordmark.tsx", `${wordmark}\n<div className="shadow-xl">`)).toEqual(["heavy-shadow"]);
  });
});

describe("the frontend's sources", () => {
  const sources = import.meta.glob<string>(
    ["/src/**/*.{ts,tsx,css}", "!/src/**/*.test.{ts,tsx}", "!/src/test/**"],
    { query: "?raw", import: "default", eager: true },
  );

  it("are all read, stylesheets included", () => {
    expect(sources["/src/main.tsx"]).toContain("createRoot");
    expect(sources["/src/styles/app.css"]).toContain('@import "./theme.css"');
    expect(sources["/src/styles/theme.css"]).toContain("@theme");
    expect(sources["/src/specimen/specimen.css"]).toContain("@import");
    expect(sources[TOKENS]).toContain("--ink");
  });

  it("carry no AI design tells", () => {
    const found = Object.entries(sources).flatMap(([path, text]) => findTells(path, text).map((r) => `${path}: ${r}`));
    expect(found).toEqual([]);
  });
});
