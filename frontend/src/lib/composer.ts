// SPDX-License-Identifier: Apache-2.0
// What the message composer knows of the steps that send a message (4f-1, the message composer design §5): which
// target a step sends to, its name in the composer's words, what its title becomes there, and a link's address checked
// as it's typed. A step it doesn't know (a third party's on the SDK's message) gets the composer and nothing more (§8,
// call 2).
import { segmentsOf } from "./pills";
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
