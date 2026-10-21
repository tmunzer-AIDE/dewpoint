// SPDX-License-Identifier: Apache-2.0
// A message's preview (4f-1, the message composer design §5.5): for Slack, Teams and Google Chat, what the TypeScript
// mirror of the target's renderer makes of the message, drawn as the target lays it out, each value shown as where it
// comes from; for the webhook, the JSON it posts; for the others, a line saying how they send it. What the target would
// cut is said under the preview. It follows every edit, named by its heading, never announced as it changes. Drawn in
// the app's own tokens, never a target's colours (no AI tells).
import { useId, type ReactNode } from "react";
import { COMPUTED, cutWords, NAMES, PLACEHOLDER, type Draft, type Target } from "../../../lib/composer";
import { googleChat, slack, teams } from "../../../lib/messages";

const NO_PREVIEW: Partial<Record<Target, string>> = {
  email: "No preview: an email is plain text, its subject the title (or the text's first line), up to 200 characters.",
};
const LAID_OUT: Partial<Record<Target, string>> = {
  slack: "Laid out as Slack shows it.",
  teams: "Laid out as a Teams card.",
  google_chat: "Laid out as Google Chat shows it.",
};
const VALUES = "A value shows where it comes from until the step runs.";

/** Text with each placeholder drawn as where its value comes from, in the code face, underlined with dots; a part a
 * formula computes as said so. In the webhook's JSON a value is in braces, as the read-only view writes one. */
function Shown({ text, says, braces = false }: { text: string; says: string[]; braces?: boolean }) {
  const out: ReactNode[] = [];
  let run = "";
  for (const char of text) {
    const n = char.codePointAt(0)! - PLACEHOLDER;
    if (n < 0 || n >= says.length) {
      run += char;
      continue;
    }
    if (run !== "") out.push(run);
    run = "";
    const words = says[n]!;
    out.push(
      words === COMPUTED ? (
        <span key={out.length} className="text-muted">{words}</span>
      ) : (
        <span key={out.length} className="font-mono text-meta underline decoration-dotted underline-offset-2">{braces ? `{${words}}` : words}</span>
      ),
    );
  }
  if (run !== "") out.push(run);
  return <>{out}</>;
}

const unescaped = (text: string) => text.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const BUTTON = "rounded-md border border-line-control px-3 py-1 text-small font-semibold";

type Mrkdwn = { text: string };
type SlackBlock =
  | { type: "section"; text?: Mrkdwn; fields?: Mrkdwn[] }
  | { type: "actions"; elements: { text: { text: string } }[] }
  | { type: "context"; elements: Mrkdwn[] };

/** Slack's blocks: the title in bold, the text, the fields two to a row, the links as buttons, the severity. */
function SlackShown({ draft }: { draft: Draft }) {
  const says = draft.says;
  const blocks = slack(draft.shown).body.blocks as SlackBlock[];
  return blocks.map((block, i) => {
    if (block.type === "actions") {
      return (
        <div key={i} className="flex flex-wrap gap-2">
          {block.elements.map((button, k) => <span key={k} className={BUTTON}><Shown text={button.text.text} says={says} /></span>)}
        </div>
      );
    }
    if (block.type === "context") return <p key={i} className="text-small text-muted"><Shown text={unescaped(block.elements[0]!.text)} says={says} /></p>;
    if (block.fields) {
      return (
        <dl key={i} className="grid grid-cols-2 gap-x-4 gap-y-2">
          {block.fields.map((field, k) => {
            const text = unescaped(field.text);
            const at = text.indexOf("\n");
            return (
              <div key={k} className="min-w-0">
                <dt className="font-semibold"><Shown text={text.slice(1, at - 1)} says={says} /></dt>
                <dd className="whitespace-pre-wrap break-words"><Shown text={text.slice(at + 1)} says={says} /></dd>
              </div>
            );
          })}
        </dl>
      );
    }
    const text = unescaped(block.text?.text ?? "");
    const title = i === 0 && Boolean(draft.shown.title); // the first section is the title's when there's one
    return (
      <p key={i} className={`whitespace-pre-wrap break-words ${title ? "font-semibold" : ""}`}>
        <Shown text={title ? text.slice(1, -1) : text} says={says} />
      </p>
    );
  });  // prettier-ignore
}

type Run = { text: string; weight?: string; size?: string; isSubtle?: boolean };
type Card = { body: { inlines: Run[] }[]; actions?: { title: string }[] };

/** Teams' card: its text runs, bolder where the card says, the severity subtle; its links as buttons under it. */
function TeamsShown({ draft }: { draft: Draft }) {
  const attachments = teams(draft.shown).body.attachments as { content: Card }[];
  const card = attachments[0]!.content;
  return (
    <>
      {card.body.map((block, i) => (
        <p key={i} className="whitespace-pre-wrap break-words">
          {block.inlines.map((run, k) => (
            <span key={k} className={[run.weight === "bolder" && "font-semibold", run.size === "medium" && "text-body-lg", run.isSubtle && "text-small text-muted"].filter(Boolean).join(" ")}>
              <Shown text={run.text} says={draft.says} />
            </span>
          ))}
        </p>
      ))}
      {card.actions && (
        <div className="flex flex-wrap gap-2">
          {card.actions.map((action, k) => <span key={k} className={BUTTON}><Shown text={action.title} says={draft.says} /></span>)}
        </div>
      )}
    </>
  );  // prettier-ignore
}

const CHAT_MARKS = /\*([^*\n]+)\*|<([^|>\n]*)\|([^>\n]*)>/g;

/** Google Chat's one text: what's between asterisks in bold, a link as its linked words. */
function ChatShown({ draft }: { draft: Draft }) {
  const text = googleChat(draft.shown).body.text as string;
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(CHAT_MARKS)) {
    out.push(<Shown key={out.length} text={text.slice(last, m.index)} says={draft.says} />);
    out.push(
      m[1] !== undefined ? (
        <strong key={out.length} className="font-semibold"><Shown text={m[1]} says={draft.says} /></strong>
      ) : (
        <span key={out.length} className="text-accent-ink underline"><Shown text={m[3] ?? ""} says={draft.says} /></span>
      ),
    );
    last = m.index + m[0].length;
  }
  out.push(<Shown key={out.length} text={text.slice(last)} says={draft.says} />);
  return <p className="whitespace-pre-wrap break-words">{out}</p>;
}

/** The webhook's JSON, as written: a part a formula gives whole is said in its place. */
function Posted({ draft }: { draft: Draft }) {
  const says = [...draft.says, COMPUTED];
  const whole = String.fromCodePoint(PLACEHOLDER + says.length - 1);
  const { title, text, fields, links, severity } = draft.shown;
  const message: Record<string, unknown> = { title: title ?? null, text, fields, links, severity: severity ?? "info" };
  for (const part of draft.computed) if (part !== "text") message[part] = "\u0000";
  const posted = JSON.stringify(message, null, 2).replaceAll('"\\u0000"', whole);
  return <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-small"><Shown text={posted} says={says} braces /></pre>;
}

export function MessagePreview({ target, draft }: { target: Target; draft: Draft }) {
  const heading = useId();
  if (target !== "slack" && target !== "teams" && target !== "google_chat" && target !== "webhook") {
    return (
      <p className="text-small text-muted">
        {NO_PREVIEW[target] ?? `No preview for ${NAMES[target]}: it sends the same message in its own form, and Simulate step says what it would cut.`}
      </p>
    );
  }
  const webhook = target === "webhook";
  const shown = draft.shown.text === "" ? (
    <p className="text-muted">Nothing to show yet: the message has no text.</p>
  ) : webhook ? <Posted draft={draft} /> : target === "slack" ? <SlackShown draft={draft} /> : target === "teams" ? <TeamsShown draft={draft} /> : <ChatShown draft={draft} />;  // prettier-ignore
  return (
    <section aria-labelledby={heading} className="flex min-w-0 flex-col gap-2">
      <h3 id={heading} className="text-small font-semibold">{webhook ? "What it posts" : `Preview in ${NAMES[target]}`}</h3>
      <p className="text-small text-muted">{webhook ? `The message as JSON, as written: nothing is cut. ${VALUES}` : `${LAID_OUT[target]} ${VALUES}`}</p>
      <div className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface-2 p-3 text-body">{shown}</div>
      {cutWords(target, draft).map((words) => (
        <p key={words} className="text-small text-warn-ink">{words}</p>
      ))}
    </section>
  );
}
