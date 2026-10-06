// SPDX-License-Identifier: Apache-2.0
/** The mechanical AI design tells of outline §6, and two token-usage rules (accent as text, the hatch behind other
 * than slate text); the checkpoint reviewer judges the rest on screen. */
const RULES: [name: string, pattern: RegExp, tokensExempt?: boolean][] = [
  // A coloured accent stripe on one side of a card, callout or row. One-pixel separators stay.
  ["accent-border", /\bborder-[lt]-(?:[2-9]|\[)|border-(?:left|top)(?:-width)?\s*:\s*(?:[2-9]|\d{2,})(?:\.\d+)?px/],
  ["gradient", /gradient/i],
  ["blur", /\bbackdrop-|backdrop-filter|\bblur-|filter\s*:\s*blur/],
  // A soft ring around a selected or failed thing. Focus rings (ring-1, ring-2) stay.
  ["halo", /\bring-(?:[3-9]|\[)|\bring-offset-(?:[3-9]|\[)|box-shadow\s*:\s*0\s+0\s+0\s+(?:[3-9]|\d{2,})px/],
  ["heavy-shadow", /\bshadow-(?:md|lg|xl|2xl)\b|drop-shadow/],
  ["decorative-motion", /\banimate-(?:pulse|bounce|ping)\b|shimmer|@keyframes\s+(?:pulse|bounce|ping)\b/],
  ["emoji", /\p{Extended_Pictographic}/u],
  ["eyebrow", /\buppercase\b|text-transform\s*:\s*uppercase|\btracking-(?:wide|wider|widest)\b|\btracking-\[0?\.(?:0[5-9]|[1-9])|letter-spacing\s*:\s*0?\.(?:0[5-9]|[1-9])/],
  ["large-radius", /\brounded(?:-[a-z]{1,2})?-(?:xl|2xl|3xl)\b|\brounded(?:-[a-z]{1,2})?-\[(?:9|[1-9]\d+)px\]|border-radius\s*:\s*(?:9|[1-9]\d+)(?:\.\d+)?px/, true],
  [
    "raw-colour",
    new RegExp(
      [
        /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/.source,
        /\b(?:rgba?|hsla?|oklch|oklab|hwb)\(/.source,
        /\b(?:bg|text|border|ring|fill|stroke|outline|divide|from|via|to|shadow|accent|caret|decoration|placeholder)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/.source,
        /\b(?:bg|text|border|fill|stroke|ring|outline)-(?:white|black)\b/.source,
      ].join("|"),
    ),
    true,
  ],
  ["marketing-copy", /\b(?:seamless(?:ly)?|supercharge[ds]?|effortless(?:ly)?|magic(?:al)?|oops)\b/i],
  // Token usage. The accent is a fill and ring colour: as text it falls under 4.5:1 (use text-accent-ink).
  ["accent-text", /\btext-accent(?![-\w])/],
  // Type comes from the scale in tokens.css (text-caption … text-h1), never Tailwind's defaults or a pixel size.
  ["type-scale", /\btext-(?:xs|sm|base|lg|xl|[2-9]xl)\b|\btext-\[\d+(?:\.\d+)?px\]/],
];

/** The hatch sits only behind slate text, the one ink held to 4.5:1 over it: a class list that draws the hatch must
 * also set `text-sim`. */
function hatchWithoutSimText(text: string): boolean {
  return [...text.matchAll(/["'`]([^"'`]*\bhatch-sim\b[^"'`]*)["'`]/g)].some((m) => !/\btext-sim\b/.test(m[1]!));
}

const TOKEN_SHEET = /(?:^|\/)src\/styles\/tokens\.css$/;

/** The rule names of the AI design tells found in one source file. A file may opt out of a rule by naming it in an
 * `ai-tells-allow: <rule>` comment, with its reason: the wordmark's tracked "FOR JUNIPER MIST" is the one known case. */
export function findTells(path: string, text: string): string[] {
  const allowed = new Set([...text.matchAll(/ai-tells-allow:\s*([a-z-]+)/g)].map((m) => m[1]));
  const isTokens = TOKEN_SHEET.test(path);
  const found = RULES.filter(([name, pattern, exempt]) => !allowed.has(name) && !(exempt && isTokens) && pattern.test(text)).map(
    ([name]) => name,
  );
  if (!allowed.has("hatch-text") && /\.tsx?$/.test(path) && hatchWithoutSimText(text)) found.push("hatch-text");
  return found;
}
