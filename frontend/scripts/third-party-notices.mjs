// SPDX-License-Identifier: Apache-2.0
// The web app's third-party notices (owner's ruling, 2026-10-06): a Vite plugin writes `third-party-notices.txt`
// into the build, so it ships in `dist` and the web image. What ships is read from the build's own metadata, never
// from the minified output: a package whose code a chunk renders, whose stylesheet the build reads (an imported CSS
// module, or a file Tailwind inlines), or whose file becomes an asset (a font). Each entry carries the package's
// declared licence and the licence and notice files it ships, in full. A shipped package without a declared licence,
// or without a licence text (its own, or a reviewed one under `licences/`), fails the build.
//   node scripts/third-party-notices.mjs --self-test
import fs from "node:fs";
import path from "node:path";

/** Virtual modules whose code ships, by their owner: Vite's preload polyfill and its loader for lazy chunks
 * (`preload-helper`, Vite's `importAnalysisBuild`), and the CommonJS helpers of the Rollup plugin Vite bundles (its
 * LICENSE.md carries the bundled plugins' licences). Any other virtual module fails. */
const VIRTUAL = {
  "\0vite/modulepreload-polyfill.js": "vite",
  "\0vite/preload-helper.js": "vite",
  "\0commonjsHelpers.js": "vite",
};

/** Packages whose published build inlines a dependency's code, by the dependency: the build's metadata sees only the
 * package, but the dependency's code ships too, so its notice must. Reviewed in the installed package: dagre 3.1.1's
 * `dist/dagre.esm.js` imports nothing and carries graphlib's `Graph` (4b, the canvas's auto layout). The dependency is
 * read from beside the package in its `node_modules` (pnpm's and npm's layouts alike); one missing fails the build. */
const INLINED = { "@dagrejs/dagre": ["@dagrejs/graphlib"] };

const LICENCE_FILE = /^(?:licen[cs]e|copying)(?:[.-].*)?$/i;
const NOTICE_FILE = /^notice(?:[.-].*)?$/i;

/**
 * The root of the package a module or file belongs to (the folder holding its package.json), or null for our own.
 * @param {string} id a Rollup module id or a file path
 * @returns {string | null}
 */
export function packageRoot(id) {
  const file = id.replace(/^\0/, "").replace(/\?.*$/, "").replaceAll("\\", "/");
  const at = file.lastIndexOf("/node_modules/");
  if (at < 0) return null;
  const rest = file.slice(at + "/node_modules/".length).split("/");
  const name = rest[0]?.startsWith("@") ? rest.slice(0, 2).join("/") : rest[0];
  return name ? `${file.slice(0, at)}/node_modules/${name}` : null;
}

/**
 * The roots of the packages a build ships, from its metadata.
 * @param {{ chunks: { modules: Record<string, number> }[], assets: { originalFileNames: string[] }[], watchFiles: string[] }} build
 *   each chunk's modules with their rendered length; each asset's source files; the files the build read
 * @param {(name: string) => string} ownerRoot the root of a package, by name (for a virtual module's owner)
 * @returns {Set<string>}
 */
export function shippedRoots(build, ownerRoot) {
  const roots = new Set();
  const add = (/** @type {string | null} */ root) => root && roots.add(root);
  for (const chunk of build.chunks) {
    for (const [id, rendered] of Object.entries(chunk.modules)) {
      const root = packageRoot(id);
      if (root) {
        if (rendered > 0 || /\.css(?:\?|$)/.test(id)) add(root); // a stylesheet ships whole; tree-shaken code doesn't
      } else if (id.startsWith("\0")) {
        const owner = VIRTUAL[/** @type {keyof typeof VIRTUAL} */ (id)];
        if (!owner) throw new Error(`third-party-notices: the virtual module ${JSON.stringify(id)} ships, and its owner is unknown`);
        if (rendered > 0) add(ownerRoot(owner));
      }
    }
  }
  for (const asset of build.assets) for (const file of asset.originalFileNames) add(packageRoot(file));
  for (const file of build.watchFiles) if (/\.css$/.test(file)) add(packageRoot(file)); // inlined into the stylesheet
  for (const root of [...roots]) {
    const at = root.lastIndexOf("/node_modules/") + "/node_modules/".length;
    for (const dependency of INLINED[/** @type {keyof typeof INLINED} */ (root.slice(at))] ?? []) add(`${root.slice(0, at)}${dependency}`);
  }
  return roots;
}

/**
 * @typedef {{ name: string, version: string, licence: string, homepage: string, files: { name: string, text: string }[] }} Notice
 */

/**
 * A shipped package's notice: its declared licence, and the licence and notice files it ships, or else the reviewed
 * text under `overrides` (`<name, / as +>@<version>.txt`), which records where it came from.
 * @param {string} root
 * @param {string} overrides
 * @returns {Notice}
 */
export function readNotice(root, overrides) {
  const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  const declared = typeof pkg.license === "string" ? pkg.license : "";
  const names = fs.readdirSync(root).filter((f) => LICENCE_FILE.test(f) || NOTICE_FILE.test(f)).sort();
  const files = names.map((name) => ({ name, text: fs.readFileSync(path.join(root, name), "utf8") }));
  if (!files.some((f) => LICENCE_FILE.test(f.name))) {
    const reviewed = path.join(overrides, `${String(pkg.name).replace("/", "+")}@${pkg.version}.txt`);
    if (fs.existsSync(reviewed)) files.unshift({ name: `LICENSE (reviewed, ${path.basename(reviewed)})`, text: fs.readFileSync(reviewed, "utf8") });
  }
  const homepage = typeof pkg.homepage === "string" ? pkg.homepage
    : typeof pkg.repository === "string" ? pkg.repository : typeof pkg.repository?.url === "string" ? pkg.repository.url : "";
  return { name: pkg.name, version: pkg.version, licence: declared, homepage, files };
}

/**
 * The notices file: every package, by name then version, with its licence texts in full.
 * @param {Notice[]} notices
 * @returns {string}
 */
export function renderNotices(notices) {
  const missing = notices.filter((n) => !n.licence || !n.files.some((f) => LICENCE_FILE.test(f.name) || f.name.startsWith("LICENSE (reviewed")));
  if (missing.length) {
    throw new Error(`third-party-notices: no declared licence or no licence text for ${missing.map((n) => `${n.name}@${n.version}`).join(", ")}`);
  }
  const unique = new Map(notices.map((n) => [`${n.name}@${n.version}`, n])); // one package reached by two paths
  const sorted = [...unique.values()].sort((a, b) => a.name.localeCompare(b.name) || a.version.localeCompare(b.version));
  const rule = "=".repeat(100);
  const head = [
    "Third-party notices: the Dewpoint web app",
    "",
    `This build ships code, styles or fonts from the ${sorted.length} packages below. Each entry gives the package, its version`,
    "and its declared licence, then the licence and notice files the package ships, in full. Generated at build time",
    "from the build's own module graph (frontend/scripts/third-party-notices.mjs).",
  ];
  const entries = sorted.map((n) => [
    rule,
    `${n.name} ${n.version}`,
    `Licence: ${n.licence}`,
    ...(n.homepage ? [n.homepage] : []),
    ...n.files.flatMap((f) => ["", `--- ${f.name} ---`, f.text.trimEnd()]),
  ].join("\n"));
  return [head.join("\n"), ...entries, ""].join("\n\n");
}

/**
 * The Vite plugin: writes `third-party-notices.txt` into the build.
 * @param {{ overrides?: string }} [options] the reviewed licence texts' folder, from the project's root
 * @returns {import("vite").Plugin}
 */
export function thirdPartyNotices({ overrides = "licences" } = {}) {
  let root = process.cwd();
  return {
    name: "dewpoint:third-party-notices",
    apply: "build",
    enforce: "post",
    configResolved(config) {
      root = config.root;
    },
    generateBundle(_, bundle) {
      const outputs = Object.values(bundle);
      const roots = shippedRoots({
        chunks: outputs.flatMap((o) => (o.type === "chunk"
          ? [{ modules: Object.fromEntries(Object.entries(o.modules).map(([id, m]) => [id, m.renderedLength])) }] : [])),
        assets: outputs.flatMap((o) => (o.type === "asset" ? [{ originalFileNames: o.originalFileNames ?? [] }] : [])),
        watchFiles: this.getWatchFiles(),
      }, (name) => fs.realpathSync(path.join(root, "node_modules", name)));
      const real = new Set([...roots].map((r) => fs.realpathSync(r))); // the store's path and a symlink's are one package
      const notices = [...real].map((r) => readNotice(r, path.join(root, overrides)));
      this.emitFile({ type: "asset", fileName: "third-party-notices.txt", source: renderNotices(notices) });
    },
  };
}

function selfTest() {
  const pnpm = "/w/node_modules/.pnpm";
  const cases = [
    // A module's package root, from the pnpm layout: scoped or not, with a query or a NUL prefix; never our own files.
    [packageRoot(`${pnpm}/react@19.1.0/node_modules/react/cjs/react.production.js`), `${pnpm}/react@19.1.0/node_modules/react`],
    [packageRoot(`${pnpm}/@radix-ui+react-menu@2.1.0/node_modules/@radix-ui/react-menu/dist/index.mjs`),
      `${pnpm}/@radix-ui+react-menu@2.1.0/node_modules/@radix-ui/react-menu`],
    [packageRoot(`\0${pnpm}/qrcode@1.5.4/node_modules/qrcode/lib/browser.js?commonjs-exports`),
      `${pnpm}/qrcode@1.5.4/node_modules/qrcode`],
    [packageRoot("/w/src/main.tsx"), null],
  ];
  for (const [got, want] of cases) if (got !== want) throw new Error(`self-test: packageRoot gave ${got}, not ${want}`);

  const owner = (name) => `/w/node_modules/${name}`;
  const shipped = shippedRoots({
    chunks: [{ modules: {
      [`${pnpm}/react@19.1.0/node_modules/react/index.js`]: 120, // rendered: ships
      [`${pnpm}/seroval@1.0.0/node_modules/seroval/dist/index.mjs`]: 0, // tree-shaken away: doesn't
      [`${pnpm}/@fontsource+inter@5.0.0/node_modules/@fontsource/inter/latin-400.css`]: 0, // CSS: ships as a stylesheet
      "\0vite/modulepreload-polyfill.js": 900, // Vite's own helper
      "\0vite/preload-helper.js": 700, // and its loader for a lazy chunk (the editor's)
      "/w/src/main.tsx": 500,
      [`${pnpm}/@dagrejs+dagre@3.1.1/node_modules/@dagrejs/dagre/dist/dagre.esm.js`]: 900, // its build inlines graphlib
    } }],
    assets: [{ originalFileNames: [`${pnpm}/@fontsource+mono@5.0.0/node_modules/@fontsource/mono/files/a.woff2`] }],
    watchFiles: [`${pnpm}/tailwindcss@4.3.3/node_modules/tailwindcss/preflight.css`, `${pnpm}/seroval@1.0.0/node_modules/seroval/x.js`],
  }, owner);
  const want = [
    `${pnpm}/@dagrejs+dagre@3.1.1/node_modules/@dagrejs/dagre`,
    `${pnpm}/@dagrejs+dagre@3.1.1/node_modules/@dagrejs/graphlib`, // beside it: its dependency, inlined in its build
    `${pnpm}/@fontsource+inter@5.0.0/node_modules/@fontsource/inter`,
    `${pnpm}/@fontsource+mono@5.0.0/node_modules/@fontsource/mono`,
    `${pnpm}/react@19.1.0/node_modules/react`,
    `${pnpm}/tailwindcss@4.3.3/node_modules/tailwindcss`,
    "/w/node_modules/vite",
  ];
  if (JSON.stringify([...shipped].sort()) !== JSON.stringify(want)) throw new Error(`self-test: shipped ${JSON.stringify([...shipped])}`);

  // An unknown virtual module fails closed: its code ships, and nothing says whose it is.
  if (!throws(() => shippedRoots({ chunks: [{ modules: { "\0mystery-helper.js": 10 } }], assets: [], watchFiles: [] }, owner))) {
    throw new Error("self-test: an unknown virtual module passed");
  }

  // A notice needs the declared licence and the licence's text; each entry names its package, version and licence.
  const react = { name: "react", version: "19.1.0", licence: "MIT", homepage: "https://react.dev/",
    files: [{ name: "LICENSE", text: "MIT License\n\nCopyright (c) Meta Platforms, Inc. and affiliates.\n" }] };
  const aria = { name: "aria-hidden", version: "1.2.6", licence: "MIT", homepage: "",
    files: [{ name: "LICENSE", text: "MIT License\n\nCopyright (c) 2017 Anton Korzunov\n" }] };
  const text = renderNotices([react, aria]);
  if (!(text.indexOf("aria-hidden 1.2.6") < text.indexOf("react 19.1.0"))) throw new Error("self-test: entries out of order");
  for (const part of ["Licence: MIT", "Copyright (c) Meta Platforms, Inc. and affiliates.", "Copyright (c) 2017 Anton Korzunov"]) {
    if (!text.includes(part)) throw new Error(`self-test: the notices miss ${part}`);
  }
  // One package reached by two paths (the pnpm store's and a symlink's) is one entry.
  if (renderNotices([react, aria, { ...react }]).split("react 19.1.0").length !== 2) throw new Error("self-test: a package listed twice");
  if (!throws(() => renderNotices([{ ...react, files: [] }]))) throw new Error("self-test: a package with no licence text passed");
  if (!throws(() => renderNotices([{ ...react, licence: "" }]))) throw new Error("self-test: a package with no declared licence passed");
  console.log("third-party-notices: self-test passed");
}

/** @param {() => unknown} f */
function throws(f) {
  try {
    f();
    return false;
  } catch {
    return true;
  }
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split("/").pop() ?? "") && process.argv[2] === "--self-test") {
  selfTest();
}
