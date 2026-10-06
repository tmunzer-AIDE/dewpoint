// SPDX-License-Identifier: Apache-2.0
// The frontend's licence gate (sub-project 4, D22): `pnpm licenses list --json [--prod]` on stdin, the scope as the
// argument. Production dependencies may carry only PROD; the whole tree (dev tools included) may add MPL-2.0. A
// licence outside its list fails the build and goes to the owner for review; only the owner adds an exception, for
// one package, version, licence and scope (EXCEPTIONS).
//   pnpm licenses list --json --prod | node scripts/licence-check.mjs prod
//   pnpm licenses list --json        | node scripts/licence-check.mjs all
//   node scripts/licence-check.mjs --self-test

const PROD = ["MIT", "ISC", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "0BSD", "OFL-1.1"];
const ALLOWED = { prod: PROD, all: [...PROD, "MPL-2.0"] };

/**
 * The owner's approved exceptions (2026-10-06, ledger): each holds for exactly that package, version and licence, in
 * its scope: "prod" also covers the whole tree, "dev" the whole tree only. A new version, another licence or a
 * dev-only package reaching production fails, and goes back to the owner. Not a blanket approval of the licence.
 * @type {{ name: string, version: string, licence: string, scope: "prod" | "dev" }[]}
 */
const EXCEPTIONS = [
  { name: "isbot", version: "5.2.2", licence: "Unlicense", scope: "prod" },
  { name: "minimatch", version: "10.2.6", licence: "BlueOak-1.0.0", scope: "dev" },
  { name: "caniuse-lite", version: "1.0.30001810", licence: "CC-BY-4.0", scope: "dev" },
  { name: "@csstools/color-helpers", version: "5.1.0", licence: "MIT-0", scope: "dev" },
  { name: "argparse", version: "2.0.1", licence: "Python-2.0", scope: "dev" },
];

/**
 * The licence an SPDX expression is used under, within `list`, or null: for `A OR B`, the first alternative that is
 * allowed; for `A AND B`, all of them, so each must be. An expression mixing AND and OR, or nesting parentheses,
 * fails closed (null): it goes to the owner.
 * @param {string} expression
 * @param {string[]} list
 * @returns {string | null}
 */
function selected(expression, list) {
  const bare = expression.replace(/^\((.*)\)$/, "$1").trim();
  if (/[()]/.test(bare) || (/\sOR\s/.test(bare) && /\sAND\s/.test(bare))) return null;
  if (/\sOR\s/.test(bare)) {
    for (const alternative of bare.split(/\s+OR\s+/)) if (selected(alternative, list)) return alternative;
    return null;
  }
  if (/\sAND\s/.test(bare)) return bare.split(/\s+AND\s+/).every((e) => selected(e, list)) ? bare : null;
  return list.includes(bare) ? bare : null;
}

/** @param {string} name @param {string} version @param {string} licence @param {"prod" | "all"} scope */
function excepted(name, version, licence, scope) {
  return EXCEPTIONS.find((e) => e.name === name && e.version === version && e.licence === licence
    && (e.scope === "prod" || scope === "all"));
}

/**
 * The scope's problems (licences outside its list, with the packages not excepted) and notes (the licence each OR
 * expression is used under; each approved exception that applies), each sorted.
 * @param {Record<string, { name: string, versions: string[] }[]>} listing pnpm's JSON: licence → packages
 * @param {"prod" | "all"} scope
 * @returns {{ problems: string[], notes: string[] }}
 */
export function review(listing, scope) {
  const problems = [];
  const notes = [];
  for (const [licence, packages] of Object.entries(listing)) {
    const choice = selected(licence, ALLOWED[scope]);
    if (choice) {
      if (choice !== licence.replace(/^\((.*)\)$/, "$1").trim() && /\sOR\s/.test(licence)) {
        for (const p of packages) for (const v of p.versions) notes.push(`${p.name}@${v} → ${choice} (from ${licence})`);
      }
      continue;
    }
    const outside = [];
    for (const p of packages) {
      for (const v of p.versions) {
        const exception = excepted(p.name, v, licence, scope);
        if (exception) notes.push(`${p.name}@${v}: ${licence}, an approved exception (${exception.scope})`);
        else outside.push(`${p.name}@${v}`);
      }
    }
    if (outside.length) problems.push(`${licence}: ${outside.join(", ")}`);
  }
  return { problems: problems.sort(), notes: notes.sort() };
}

function selfTest() {
  const pkg = (name, version = "1.0.0") => [{ name, versions: [version] }];
  /** [listing, scope, problems, the report's other lines (choices and exceptions), in order] */
  const cases = [
    [{ MIT: pkg("a"), "OFL-1.1": pkg("font") }, "prod", 0, []],
    [{ "GPL-3.0": pkg("copyleft") }, "all", 1, []],
    [{ "MPL-2.0": pkg("axe-core") }, "prod", 1, []],
    [{ "MPL-2.0": pkg("axe-core") }, "all", 0, []],
    [{ Unlicense: pkg("left-pad") }, "prod", 1, []],
    // OR: allowed when an alternative is, and the report names the one selected; AND needs every licence.
    [{ "(MIT OR CC0-1.0)": pkg("type-fest", "4.41.0") }, "prod", 0, ["type-fest@4.41.0 → MIT (from (MIT OR CC0-1.0))"]],
    [{ "(CC0-1.0 OR Apache-2.0)": pkg("second") }, "prod", 0, ["second@1.0.0 → Apache-2.0 (from (CC0-1.0 OR Apache-2.0))"]],
    [{ "(GPL-3.0 OR CC0-1.0)": pkg("neither") }, "all", 1, []],
    [{ "(MIT AND CC-BY-4.0)": pkg("both") }, "all", 1, []],
    [{ "(MIT AND ISC)": pkg("both") }, "prod", 0, []],
    [{ "(GPL-3.0 OR CC-BY-4.0) AND (Unlicense OR MIT)": pkg("mixed") }, "prod", 1, []], // mixed: fail closed
    // The owner's exceptions (2026-10-06): exactly that package, version, licence and scope.
    [{ Unlicense: pkg("isbot", "5.2.2") }, "prod", 0, ["isbot@5.2.2: Unlicense, an approved exception (prod)"]],
    [{ Unlicense: pkg("isbot", "5.2.2") }, "all", 0, ["isbot@5.2.2: Unlicense, an approved exception (prod)"]],
    [{ Unlicense: pkg("isbot", "5.2.3") }, "prod", 1, []], // another version: back to the owner
    [{ Unlicense: [{ name: "isbot", versions: ["5.2.2", "5.3.0"] }] }, "prod", 1, // one version not approved
      ["isbot@5.2.2: Unlicense, an approved exception (prod)"]],
    [{ "BlueOak-1.0.0": pkg("minimatch", "10.2.6") }, "all", 0, ["minimatch@10.2.6: BlueOak-1.0.0, an approved exception (dev)"]],
    [{ "BlueOak-1.0.0": pkg("minimatch", "10.2.6") }, "prod", 1, []], // a dev-only exception in production
    [{ "GPL-3.0": pkg("argparse", "2.0.1") }, "all", 1, []], // the approved version under another licence
    [{ "CC-BY-4.0": pkg("caniuse-lite", "1.0.30001810"), "MIT-0": pkg("@csstools/color-helpers", "5.1.0"),
       "Python-2.0": pkg("argparse", "2.0.1") }, "all", 0, [
      "@csstools/color-helpers@5.1.0: MIT-0, an approved exception (dev)",
      "argparse@2.0.1: Python-2.0, an approved exception (dev)",
      "caniuse-lite@1.0.30001810: CC-BY-4.0, an approved exception (dev)",
    ]],
  ];
  for (const [listing, scope, count, notes] of cases) {
    const found = review(/** @type {any} */ (listing), /** @type {"prod" | "all"} */ (scope));
    const label = `${scope} ${JSON.stringify(listing)}`;
    if (found.problems.length !== count) throw new Error(`self-test: ${label} gave ${found.problems.length} problems`);
    if (JSON.stringify(found.notes) !== JSON.stringify(notes)) throw new Error(`self-test: ${label} noted ${JSON.stringify(found.notes)}`);
  }
  console.log("licence-check: self-test passed");
}

async function main() {
  const scope = process.argv[2];
  if (scope === "--self-test") return selfTest();
  if (scope !== "prod" && scope !== "all") throw new Error("usage: licence-check.mjs prod|all|--self-test");
  let text = "";
  for await (const chunk of process.stdin) text += chunk;
  const { problems, notes } = review(JSON.parse(text), scope);
  for (const line of notes) console.log(`licence-check: ${line}`);
  if (problems.length === 0) return console.log(`licence-check: ${scope} dependencies within D22's list`);
  console.error(`licence-check: ${scope} dependencies outside D22's list, for the owner's review:`);
  for (const line of problems) console.error(`  ${line}`);
  process.exitCode = 1;
}

await main();
