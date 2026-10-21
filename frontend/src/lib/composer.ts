// SPDX-License-Identifier: Apache-2.0
// What the message composer knows of the steps that send a message (4f-1, the message composer design §5): which
// target a step sends to, its name in the composer's words, what its title becomes there, a link's address checked as
// it's typed, and the message as a preview draws it, with what its target would cut. A step it doesn't know (a third
// party's on the SDK's message) gets the composer and nothing more (§8, call 2).
import { fixedOf, kindOf } from "./config";
import { CHAT_BUDGET, fitted, googleChat, SLACK, slack, TEAMS_BUDGET, teams, type Message, type Severity } from "./messages";
import { headOf, segmentsOf } from "./pills";
import { isObject } from "./schemaForm";
import type { NodeType } from "./workflows";

export type Target = "slack" | "teams" | "google_chat" | "webhook" | "email" | "syslog" | "pagerduty" | "servicenow";

const STEPS = new Map<string, Target>([
  ["slack.send_message", "slack"],
  ["teams.send_message", "teams"],
  ["google_chat.send_message", "google_chat"],
  ["webhook.send_message", "webhook"],
  ["email.send_message", "email"],
  ["syslog.send_message", "syslog"],
  ["pagerduty.trigger_alert", "pagerduty"],
  ["servicenow.create_incident", "servicenow"],
]);

export const NAMES: Record<Target, string> = {
  slack: "Slack", teams: "Teams", google_chat: "Google Chat", webhook: "the webhook", email: "email", syslog: "syslog",
  pagerduty: "PagerDuty", servicenow: "ServiceNow",
};  // prettier-ignore

/** What the title becomes, where that's more than a title (§5.2). */
const TITLES: Partial<Record<Target, string>> = {
  email: "the email's subject",
  pagerduty: "the alert's summary",
  servicenow: "the incident's short description",
};

export const targetOf = (type: NodeType | undefined): Target | null => (type ? (STEPS.get(type.type) ?? null) : null);

/** Options' line on a message step: the message is on Setup (§5.1). */
export const optionsLine = (target: Target | null): string =>
  `The message is on Setup; what only ${target ? NAMES[target] : "this step"} takes stays here.`;

/** The title's hint: optional, and what it becomes where it matters (§5.2). */
export const titleHint = (target: Target | null): string => {
  const becomes = target ? TITLES[target] : undefined;
  return becomes ? `optional · ${becomes}` : "optional";
};

export const LINK_WORDS = "A link's address starts with http:// or https://.";

/** What's wrong with a link's address that starts with written text: the SDK's link starts with http:// or https://
 * (sdk/messages.py's LINK_URL). One that starts with a value, or a formula, is checked when the step runs (§5.3). */
export function linkProblem(value: unknown): string | null {
  const start = segmentsOf(value)?.texts[0] ?? "";
  return start !== "" && !/^https?:\/\//.test(start) ? LINK_WORDS : null;
}

/** Why another field or link can't be added (§5.3). */
export const capWords = (noun: "field" | "link", max: number): string => `A message takes up to ${max} ${noun}s: remove one to add another.`;

export const COMPUTED = "Computed when the step runs";

/** Where a value comes from, as a preview says it: `check.site` for a step's output, `trigger.events[0].ap` (§5.5). */
export function sourceText(path: string): string {
  const { head, rest } = headOf(path);
  return rest === "" ? head : rest.startsWith("[") ? `${head}${rest}` : `${head}.${rest}`;
}

/** The message as a preview draws it (§5.5): `shown` holds a placeholder for each value, a character of Unicode's
 * private use plane 15 that no renderer escapes, splits or cuts through, `says` what each one says, in order; `bare`
 * is the message without them, which the cut maths count (§5.2). A part a formula computes is one placeholder, and
 * none of it is counted (§5.1). */
export interface Draft {
  shown: Message;
  bare: Message;
  says: string[];
  computed: string[]; // the parts a formula or an earlier step's value gives whole: the webhook's JSON says so
}

export const PLACEHOLDER = 0xf0000;

/** A list or a severity a formula or a value from an earlier step gives: known when the step runs. */
const isComputed = (value: unknown): boolean => kindOf(value) === "cel" || kindOf(value) === "ref" || kindOf(value) === "template";

type Row = { label: string; value: string } | { label: string; url: string };

export function draftOf(config: Record<string, unknown>): Draft {
  const says: string[] = [];
  const computed = ["text", "fields", "links", "severity"].filter((part) => isComputed(config[part]) && !(part === "text" && kindOf(config.text) !== "cel"));
  const hold = (words: string): string => String.fromCodePoint(PLACEHOLDER + says.push(words) - 1);
  const text = (value: unknown): { shown: string; bare: string } => {
    if (kindOf(value) === "cel") return { shown: hold(COMPUTED), bare: "" };
    const s = segmentsOf(value);
    if (s === null) return { shown: "", bare: "" };
    return { shown: s.texts.map((t, i) => (s.pills[i] ? t + hold(sourceText(s.pills[i].ref)) : t)).join(""), bare: s.texts.join("") };
  };
  const rows = (value: unknown, second: "value" | "url"): { shown: Row[]; bare: Row[] } => {
    if (isComputed(value)) return { shown: [{ label: hold(COMPUTED), [second]: "" } as Row], bare: [] };
    const items = fixedOf(value);
    const each = (Array.isArray(items) ? (items as unknown[]) : []).map((item) => {
      const row = isObject(item) ? item : {};
      return { label: text(row.label), other: text(row[second]) };
    });
    return {
      shown: each.map((row) => ({ label: row.label.shown, [second]: row.other.shown }) as Row),
      bare: each.map((row) => ({ label: row.label.bare, [second]: row.other.bare }) as Row),
    };
  };
  const title = config.title === undefined || config.title === null ? null : text(config.title);
  const body = text(config.text);
  const fields = rows(config.fields, "value");
  const links = rows(config.links, "url");
  const fixed = fixedOf(config.severity);
  const severity = isComputed(config.severity) ? null : typeof fixed === "string" ? (fixed as Severity) : "info";
  const shown: Message = {
    title: title?.shown ?? null, text: body.shown, fields: fields.shown as Message["fields"], links: links.shown as Message["links"],
    severity: severity ?? (hold(COMPUTED) as Severity),
  };  // prettier-ignore
  const bare: Message = {
    title: title?.bare ?? null, text: body.bare, fields: fields.bare as Message["fields"], links: links.bare as Message["links"],
    severity: severity ?? "info",
  };  // prettier-ignore
  return { shown, bare, says, computed };
}

/** A value cut, as the composer and Simulate step say it (§5.7). */
export function cutName(name: string): string {
  if (name === "title" || name === "text" || name === "description") return `the ${name}`;
  const part = /^(fields|links)\[(\d+)\](?:\.(label|value))?$/.exec(name);
  if (!part) return name;
  const n = Number(part[2]) + 1;
  const noun = part[1] === "fields" ? "field" : "link";
  return part[3] ? `${noun} ${n}'s ${part[3]}` : `${noun} ${n} (left out)`;
}

const counted = (n: number): string => n.toLocaleString("en-US");

/** Slack's limit for a value it cut, in characters: a field's value has what its label leaves (plugins/slack). */
function slackLimit(name: string, message: Message): number {
  const field = /^fields\[(\d+)\]\.value$/.exec(name);
  if (field) return SLACK.FIELD_MAX - [...fitted(message.fields![Number(field[1])]!.label, SLACK.LABEL_MAX)[0]].length - 3;
  if (name === "title") return SLACK.SECTION_MAX - 2;
  if (name.endsWith(".label")) return name.startsWith("links") ? SLACK.BUTTON_MAX : SLACK.LABEL_MAX;
  return SLACK.SECTION_MAX;
}

/** What Teams or Google Chat would shorten, in the order their levels tighten them, and how many links they'd leave
 * out. */
function shortened(truncated: string[]): string {
  const parts = [
    truncated.includes("text") && "the text",
    truncated.some((n) => /^fields\[\d+\]\.value$/.test(n)) && "the fields' values",
    truncated.includes("title") && "the title",
    truncated.some((n) => n.endsWith(".label")) && "the labels",
  ].filter((p): p is string => p !== false);
  const left = truncated.filter((n) => /^links\[\d+\]$/.test(n)).length;
  const words: string[] = [];
  if (parts.length > 0) {
    const first = `${parts[0]![0]!.toUpperCase()}${parts[0]!.slice(1)}`;
    words.push(parts.length === 1 ? `${first} would be shortened.` : `${first} would be shortened first, then ${parts.slice(1).join(" and ")}.`);
  }
  if (left > 0) words.push(left === 1 ? "A link would be left out." : `${left} links would be left out.`);
  return words.join(" ");
}

/** What the target would cut of the message, its values left out (§5.5): Slack each value with its limit, Teams and
 * Google Chat the body's size against their budget. A warning, never an error. */
export function cutWords(target: Target, draft: Draft): string[] {
  if (target === "slack") return slack(draft.bare).truncated.map((name) => `Slack will cut ${cutName(name)} at ${counted(slackLimit(name, draft.bare))} characters.`);
  if (target !== "teams" && target !== "google_chat") return [];
  const { truncated, size = 0 } = target === "teams" ? teams(draft.bare) : googleChat(draft.bare);
  if (truncated.length === 0) return [];
  const budget = target === "teams" ? TEAMS_BUDGET : CHAT_BUDGET;
  return [`About ${counted(Math.round(size / 1000) * 1000)} bytes before its values: ${NAMES[target]} takes ${counted(budget)}. ${shortened(truncated)}`];
}

/** Under Slack's text: its length as Slack's renderer counts it, escaped, before its values (§5.2). */
export function slackCount(draft: Draft): string {
  const n = [...fitted(draft.bare.text, Number.MAX_SAFE_INTEGER)[0]].length;
  if (n > SLACK.SECTION_MAX) return `${counted(n)} characters. Slack shows the first ${counted(SLACK.SECTION_MAX)} and ends them with "…".`;
  return `${counted(n)} characters${draft.shown.text !== draft.bare.text ? ", before its values" : ""}. Slack shows up to ${counted(SLACK.SECTION_MAX)}.`;
}

/** Whether the target would cut the text, its values left out: said under the text too (§5.5). */
export function cutsText(target: Target, draft: Draft): boolean {
  const render = target === "slack" ? slack : target === "teams" ? teams : target === "google_chat" ? googleChat : null;
  return render !== null && render(draft.bare).truncated.includes("text");
}
