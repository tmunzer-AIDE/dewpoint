// SPDX-License-Identifier: Apache-2.0
// The frontend's licence gate (sub-project 4, D22): `pnpm licenses list --json [--prod]` on stdin, the scope as the
// argument. Production dependencies may carry only PROD; the whole tree (dev tools included) may add MPL-2.0. A
// licence outside its list fails the build and goes to the owner for review: never add an exception without it.
//   pnpm licenses list --json --prod | node scripts/licence-check.mjs prod
//   pnpm licenses list --json        | node scripts/licence-check.mjs all
//   node scripts/licence-check.mjs --self-test

const PROD = ["MIT", "ISC", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "0BSD", "OFL-1.1"];
const ALLOWED = { prod: PROD, all: [...PROD, "MPL-2.0"] };

/**
 * Whether an SPDX expression is within `list`: `A OR B` when either is (the package may be used under it), `A AND B`
 * when both are. An expression mixing AND and OR, or nesting parentheses, fails closed: it goes to the owner.
 * @param {string} expression
 * @param {string[]} list
 */
function allowed(expression, list) {
  const bare = expression.replace(/^\((.*)\)$/, "$1").trim();
  if (/[()]/.test(bare) || (/\sOR\s/.test(bare) && /\sAND\s/.test(bare))) return false;
  if (/\sOR\s/.test(bare)) return bare.split(/\s+OR\s+/).some((e) => allowed(e, list));
  if (/\sAND\s/.test(bare)) return bare.split(/\s+AND\s+/).every((e) => allowed(e, list));
  return list.includes(bare);
}

/**
 * The licences outside the scope's list, each with its packages.
 * @param {Record<string, { name: string, versions: string[] }[]>} listing pnpm's JSON: licence → packages
 * @param {"prod" | "all"} scope
 * @returns {string[]}
 */
export function unexpected(listing, scope) {
  return Object.entries(listing)
    .filter(([licence]) => !allowed(licence, ALLOWED[scope]))
    .map(([licence, packages]) => `${licence}: ${packages.map((p) => `${p.name}@${p.versions.join("|")}`).join(", ")}`)
    .sort();
}

function selfTest() {
  const pkg = (name) => [{ name, versions: ["1.0.0"] }];
  const cases = [
    [{ MIT: pkg("a"), "OFL-1.1": pkg("font") }, "prod", 0],
    [{ "GPL-3.0": pkg("copyleft") }, "all", 1],
    [{ "MPL-2.0": pkg("axe-core") }, "prod", 1],
    [{ "MPL-2.0": pkg("axe-core") }, "all", 0],
    [{ Unlicense: pkg("isbot") }, "prod", 1],
    [{ "(MIT OR CC0-1.0)": pkg("type-fest") }, "prod", 0],
    [{ "(GPL-3.0 OR CC0-1.0)": pkg("neither") }, "all", 1],
    [{ "(MIT AND CC-BY-4.0)": pkg("both") }, "all", 1],
    [{ "(MIT AND ISC)": pkg("both") }, "prod", 0],
    [{ "(GPL-3.0 OR CC-BY-4.0) AND (Unlicense OR MIT)": pkg("mixed") }, "prod", 1], // mixed: fail closed
  ];
  for (const [listing, scope, count] of cases) {
    const found = unexpected(/** @type {any} */ (listing), /** @type {"prod" | "all"} */ (scope));
    if (found.length !== count) throw new Error(`self-test: ${scope} ${JSON.stringify(listing)} gave ${found.length}`);
  }
  console.log("licence-check: self-test passed");
}

async function main() {
  const scope = process.argv[2];
  if (scope === "--self-test") return selfTest();
  if (scope !== "prod" && scope !== "all") throw new Error("usage: licence-check.mjs prod|all|--self-test");
  let text = "";
  for await (const chunk of process.stdin) text += chunk;
  const found = unexpected(JSON.parse(text), scope);
  if (found.length === 0) return console.log(`licence-check: ${scope} dependencies within D22's list`);
  console.error(`licence-check: ${scope} dependencies outside D22's list, for the owner's review:`);
  for (const line of found) console.error(`  ${line}`);
  process.exitCode = 1;
}

await main();
