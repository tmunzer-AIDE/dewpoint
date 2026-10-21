// SPDX-License-Identifier: Apache-2.0
// The message the chat targets send (plugins-3 D18; editor 4f-1, the message composer design §4.2), and Slack's, Teams'
// and Google Chat's renderers mirrored from the plugins (`render()` in plugins/slack, plugins/teams and
// plugins/google_chat; sdk/messages.py's `cut`): a preview lays a message out as its target will, and says what it would
// cut. Held to the plugins' own output by the shared cases (src/test/messageCases.json): a renderer changed there fails
// messages.test.ts until this follows. Characters are counted in code points, as Python counts them.

export type Severity = "info" | "success" | "warning" | "critical";

export interface Message {
  title?: string | null;
  text: string;
  fields?: { label: string; value: string }[];
  links?: { label: string; url: string }[];
  severity?: Severity;
}

/** What a target is sent, the names of the values it cut, and for Teams and Google Chat the body's size in bytes before
 * anything was shortened. */
export interface Rendered {
  body: Record<string, unknown>;
  truncated: string[];
  size?: number;
}

export const MARK = "…"; // what a cut value ends with

const length = (text: string): number => [...text].length;
const encoder = new TextEncoder();
export const bytesOf = (text: string): number => encoder.encode(text).length;
/** The body as the plugins send it: compact JSON, UTF-8 (httpx's `encode_json`). */
const encodedSize = (body: unknown): number => bytesOf(JSON.stringify(body));

/** `text` within `limit` characters (or UTF-8 bytes), ending with MARK when it had to be cut; whether it was. */
export function cut(text: string, limit: number, unit: "chars" | "bytes" = "chars"): [string, boolean] {
  const chars = [...text];
  if (unit === "chars") return chars.length <= limit ? [text, false] : [chars.slice(0, Math.max(0, limit - 1)).join("") + MARK, true];
  if (bytesOf(text) <= limit) return [text, false];
  const budget = limit - bytesOf(MARK);
  const kept: string[] = [];
  let size = 0;
  for (const char of chars) {
    size += bytesOf(char);
    if (size > budget) break;
    kept.push(char);
  }
  return [kept.join("") + MARK, true];
}

/** Collects the names of the values cut, as each renderer's `kept` does. */
function cutter() {
  const truncated: string[] = [];
  const kept = (name: string, [value, was]: [string, boolean]): string => {
    if (was) truncated.push(name);
    return value;
  };
  return { truncated, kept };
}

// Slack (plugins/slack): Block Kit, each value escaped and cut within Slack's limits.
export const SLACK = { SECTION_MAX: 3000, FIELD_MAX: 2000, FIELDS_A_SECTION: 10, BUTTON_MAX: 75, LABEL_MAX: 300 };

const escape = (char: string): string => (char === "&" ? "&amp;" : char === "<" ? "&lt;" : char === ">" ? "&gt;" : char);

/** `raw` escaped, within `limit` characters: cut before an escape rather than through one, and marked. */
export function fitted(raw: string, limit: number): [string, boolean] {
  const parts = [...raw].map(escape);
  const escaped = parts.join("");
  if (length(escaped) <= limit) return [escaped, false];
  const kept: string[] = [];
  let size = 0;
  for (const part of parts) {
    if (size + length(part) > limit - length(MARK)) break;
    kept.push(part);
    size += length(part);
  }
  return [kept.join("") + MARK, true];
}

const mrkdwn = (text: string) => ({ type: "mrkdwn", text, verbatim: true });

export function slack(message: Message): Rendered {
  const { SECTION_MAX, FIELD_MAX, FIELDS_A_SECTION, BUTTON_MAX, LABEL_MAX } = SLACK;
  const { truncated, kept } = cutter();
  const blocks: Record<string, unknown>[] = [];
  if (message.title) blocks.push({ type: "section", text: mrkdwn(`*${kept("title", fitted(message.title, SECTION_MAX - 2))}*`) });
  blocks.push({ type: "section", text: mrkdwn(kept("text", fitted(message.text, SECTION_MAX))) });
  const fields = (message.fields ?? []).map((f, i) => {
    const label = kept(`fields[${i}].label`, fitted(f.label, LABEL_MAX));
    const value = kept(`fields[${i}].value`, fitted(f.value, FIELD_MAX - length(label) - 3));
    return mrkdwn(`*${label}*\n${value}`);
  });
  for (let start = 0; start < fields.length; start += FIELDS_A_SECTION) {
    blocks.push({ type: "section", fields: fields.slice(start, start + FIELDS_A_SECTION) });
  }
  const links = message.links ?? [];
  if (links.length > 0) {
    const buttons = links.map((link, i) => ({
      type: "button", text: { type: "plain_text", text: kept(`links[${i}].label`, cut(link.label, BUTTON_MAX)), emoji: false },
      url: link.url, action_id: `link_${i}`,
    }));  // prettier-ignore
    blocks.push({ type: "actions", elements: buttons });
  }
  blocks.push({ type: "context", elements: [mrkdwn(`Severity: ${message.severity ?? "info"}`)] });
  const fallback = message.title ? `${message.title}: ${message.text}` : message.text;
  return { body: { text: fitted(fallback, SECTION_MAX)[0], blocks }, truncated };
}

// Teams and Google Chat: the whole body within a budget of bytes, each value tighter at each level until it fits.
// A level: title characters, text bytes, field value bytes, label characters, links kept. The first cuts nothing.
type Level = readonly [number, number, number, number, number];
const LEVELS: readonly Level[] = [
  [1000, 160_000, 40_000, 200, 10],
  [1000, 16_000, 2000, 200, 10],
  [500, 8000, 600, 100, 10],
  [200, 4000, 200, 60, 5],
  [100, 1000, 60, 30, 2],
  [60, 200, 20, 20, 0],
];
export const TEAMS_BUDGET = 24_000;
export const CHAT_BUDGET = 30_000;

/** The first level's body that fits the budget (the last always fits), with the size of the first, uncut. */
function withinBudget(budget: number, make: (level: Level) => Omit<Rendered, "size">): Rendered {
  let made = make(LEVELS[0]!);
  const size = encodedSize(made.body);
  if (size <= budget) return { ...made, size };
  for (const level of LEVELS.slice(1)) {
    made = make(level);
    if (encodedSize(made.body) <= budget) break;
  }
  return { ...made, size };
}

const runs = (...each: Record<string, unknown>[]) => ({ type: "RichTextBlock", inlines: each.map((run) => ({ type: "TextRun", ...run })) });

function teamsCard(message: Message, [titleMax, textMax, valueMax, labelMax, linksKept]: Level): Omit<Rendered, "size"> {
  const { truncated, kept } = cutter();
  const body: Record<string, unknown>[] = [];
  if (message.title) body.push(runs({ text: kept("title", cut(message.title, titleMax)), weight: "bolder", size: "medium" }));
  body.push(runs({ text: kept("text", cut(message.text, textMax, "bytes")) }));
  (message.fields ?? []).forEach((field, i) => {
    const label = kept(`fields[${i}].label`, cut(field.label, labelMax));
    const value = kept(`fields[${i}].value`, cut(field.value, valueMax, "bytes"));
    body.push(runs({ text: label, weight: "bolder" }, { text: ": " }, { text: value }));
  });
  body.push(runs({ text: `Severity: ${message.severity ?? "info"}`, isSubtle: true, size: "small" }));
  const card: Record<string, unknown> = { $schema: "http://adaptivecards.io/schemas/adaptive-card.json", type: "AdaptiveCard", version: "1.2", body };
  const links = message.links ?? [];
  const actions = links.slice(0, linksKept).map((link, i) => ({ type: "Action.OpenUrl", title: kept(`links[${i}].label`, cut(link.label, labelMax)), url: link.url }));
  truncated.push(...links.slice(linksKept).map((_, i) => `links[${linksKept + i}]`));
  if (actions.length > 0) card.actions = actions;
  return { body: { type: "message", attachments: [{ contentType: "application/vnd.microsoft.card.adaptive", contentUrl: null, content: card }] }, truncated };
}

export const teams = (message: Message): Rendered => withinBudget(TEAMS_BUDGET, (level) => teamsCard(message, level));

// Google Chat: one text message; < and > shown as ＜ ＞, so a value can't become a link or a mention.
const neutral = (text: string): string => text.replace(/</g, "＜").replace(/>/g, "＞");

function chatText(message: Message, [titleMax, textMax, valueMax, labelMax, linksKept]: Level): Omit<Rendered, "size"> {
  const { truncated, kept } = cutter();
  const text = kept("text", cut(neutral(message.text), textMax, "bytes"));
  const head = message.title ? `*${kept("title", cut(neutral(message.title), titleMax))}*\n${text}` : text;
  const fields = (message.fields ?? []).map(
    (f, i) => `*${kept(`fields[${i}].label`, cut(neutral(f.label), labelMax))}*: ${kept(`fields[${i}].value`, cut(neutral(f.value), valueMax, "bytes"))}`,
  );
  const links = message.links ?? [];
  const linked = links
    .slice(0, linksKept)
    .map((link, i) => `<${link.url.replace(/\|/g, "%7C")}|${kept(`links[${i}].label`, cut(neutral(link.label), labelMax))}>`);
  truncated.push(...links.slice(linksKept).map((_, i) => `links[${linksKept + i}]`));
  const sections = [head, ...[fields, linked].filter((part) => part.length > 0).map((part) => part.join("\n")), `Severity: ${message.severity ?? "info"}`];
  return { body: { text: sections.join("\n\n") }, truncated };
}

export const googleChat = (message: Message): Rendered => withinBudget(CHAT_BUDGET, (level) => chatText(message, level));
