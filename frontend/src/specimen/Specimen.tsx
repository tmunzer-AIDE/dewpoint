// SPDX-License-Identifier: Apache-2.0
/* The token specimen (sub-project 4, slice 4a): every token, its contrast floors, type, states and the meaning
   colours, in a light and a dark panel, for the owner's approval. Development only: `vite build` never includes it. */
import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Mark, Wordmark } from "../components/Mark";
import { contrast, over, parseColour } from "../styles/contrast";
import { BUTTON_STATE_NAMES, BUTTON_STATES, COLOURS, PAIRS, type ButtonVariant } from "../styles/tokenNames";

// Literal class names, so Tailwind generates them (it can't see `bg-${name}`).
const BG: Record<string, string> = {
  ground: "bg-ground", surface: "bg-surface", "surface-2": "bg-surface-2", "surface-hover": "bg-surface-hover",
  "surface-pressed": "bg-surface-pressed", ink: "bg-ink", muted: "bg-muted", line: "bg-line",
  "line-strong": "bg-line-strong", "line-control": "bg-line-control", edge: "bg-edge", accent: "bg-accent",
  "accent-hover": "bg-accent-hover", "accent-pressed": "bg-accent-pressed", "accent-ink": "bg-accent-ink",
  "accent-soft": "bg-accent-soft", "on-accent": "bg-on-accent", focus: "bg-focus", "focus-rail": "bg-focus-rail",
  "warn-bg": "bg-warn-bg", "warn-line": "bg-warn-line", "warn-ink": "bg-warn-ink", danger: "bg-danger",
  "danger-hover": "bg-danger-hover", "danger-pressed": "bg-danger-pressed", "danger-bg": "bg-danger-bg", "on-danger": "bg-on-danger", ok: "bg-ok",
  "ok-bg": "bg-ok-bg", live: "bg-live", "live-hover": "bg-live-hover", "live-pressed": "bg-live-pressed",
  "live-bg": "bg-live-bg", "on-live": "bg-on-live", sim: "bg-sim", "sim-bg": "bg-sim-bg", "sim-hatch": "bg-sim-hatch",
  brand: "bg-brand", rail: "bg-rail", "rail-ink": "bg-rail-ink", "rail-ink-strong": "bg-rail-ink-strong",
  "rail-dim": "bg-rail-dim", "rail-active": "bg-rail-active", "rail-line": "bg-rail-line",
  "disabled-ink": "bg-disabled-ink", "disabled-bg": "bg-disabled-bg", "disabled-line": "bg-disabled-line",
  overlay: "bg-overlay",
};
const FG: Record<string, string> = {
  ink: "text-ink", muted: "text-muted", "line-control": "text-line-control", focus: "text-focus", edge: "text-edge",
  "accent-ink": "text-accent-ink", "on-accent": "text-on-accent", "warn-ink": "text-warn-ink", danger: "text-danger",
  "on-danger": "text-on-danger", ok: "text-ok", live: "text-live", "live-hover": "text-live-hover", "on-live": "text-on-live",
  sim: "text-sim",
  "rail-ink": "text-rail-ink", "rail-dim": "text-rail-dim", "rail-ink-strong": "text-rail-ink-strong",
  "focus-rail": "text-focus-rail", brand: "text-brand",
};

const TRANSLUCENT = new Set(["rail-active", "rail-line", "overlay"]);

const BORDER: Record<string, string> = {
  accent: "border-accent", "accent-hover": "border-accent-hover", "accent-pressed": "border-accent-pressed",
  "line-strong": "border-line-strong", sim: "border-sim", live: "border-live", "live-hover": "border-live-hover",
  "live-pressed": "border-live-pressed", danger: "border-danger", "danger-hover": "border-danger-hover",
  "danger-pressed": "border-danger-pressed",
};

type Theme = "light" | "dark";

/** The panel's token values, read once it is in the document (empty outside a browser). */
function useTokens(ref: RefObject<HTMLElement | null>): (name: string) => string {
  const [values, setValues] = useState<Record<string, string>>({});
  useLayoutEffect(() => {
    if (!ref.current) return;
    const style = getComputedStyle(ref.current);
    setValues(Object.fromEntries(COLOURS.map((n) => [n, style.getPropertyValue(`--${n}`).trim()])));
  }, [ref]);
  return (name) => values[name] ?? "";
}

function ratioOf(get: (n: string) => string, fg: string, bg: string): number | null {
  try {
    const rail = parseColour(get("rail"));
    const back = parseColour(get(bg));
    const opaqueBack = back[3] < 1 ? over(back, rail) : back;
    const front = parseColour(get(fg));
    return contrast(front[3] < 1 ? over(front, opaqueBack) : front, opaqueBack);
  } catch {
    return null;
  }
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-h3 font-semibold">{title}</h2>
      {children}
    </div>
  );
}

function Swatches({ get }: { get: (n: string) => string }) {
  return (
    <Section title="Colour">
      <div className="grid grid-cols-4 gap-2">
        {COLOURS.map((name) => (
          <div key={name} data-token={name} className="flex items-center gap-2 rounded-lg border border-line bg-surface p-2">
            {/* Translucent tokens are drawn where they're used: over the rail. */}
            <span className={`shrink-0 rounded-md ${TRANSLUCENT.has(name) ? "bg-rail p-1" : ""}`}>
              <span className={`block h-8 w-8 rounded-md border border-line ${BG[name]} ${TRANSLUCENT.has(name) ? "h-6 w-6" : ""}`} />
            </span>
            <span className="flex min-w-0 flex-col">
              <span className="font-mono text-meta">{name}</span>
              <span className="font-mono text-caption text-muted">{get(name) || "—"}</span>
            </span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Pairs({ get }: { get: (n: string) => string }) {
  return (
    <Section title="Contrast floors (text 4.5:1, boundaries and graphics 3:1)">
      <div className="grid grid-cols-3 gap-2">
        {PAIRS.map(([fg, bg, min]) => {
          const r = ratioOf(get, fg, bg);
          return (
            <div key={`${fg}/${bg}`} data-testid="pair" className="flex items-center gap-3 rounded-lg border border-line bg-surface p-2">
              <span className={`rounded-md bg-rail p-0.5`}>
                <span className={`flex h-9 w-14 items-center justify-center gap-1.5 rounded-sm ${BG[bg]} ${FG[fg] ?? ""}`}>
                  <span className="text-body font-medium">Aa</span>
                  <span className="h-4 w-0.5 bg-current" />
                </span>
              </span>
              <span className="flex flex-col">
                <span className="font-mono text-caption">{fg} on {bg}</span>
                <span className={`font-mono text-meta ${r !== null && r < min ? "text-danger" : "text-muted"}`}>
                  {r === null ? "—" : `${r.toFixed(2)}:1`} · floor {min}:1
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function Type() {
  return (
    <Section title="Type">
      <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
        <h1 className="text-h1 font-semibold">Workflows · h1 22 Schibsted Grotesk 600</h1>
        <h2 className="text-h2 font-semibold">New workflow · h2 20</h2>
        <h3 className="text-h3 font-semibold">The agent wants to restart Paris-Opera-AP-03 · h3 18</h3>
        <p className="font-mono text-title font-semibold">triage_ap · title 16 JetBrains Mono 600</p>
        <p className="text-body-lg">Organization ID · body-lg 15 Instrument Sans</p>
        <p className="text-body">Runs start from a trigger, a schedule, or Run now. · body 14</p>
        <p className="text-small text-muted">Disabled workflows keep their versions and history. · small 13 muted</p>
        <p className="text-meta text-muted">started 09:41:12 UTC · 38 s · meta 12</p>
        <p className="text-caption">approval · caption 11</p>
        <p className="font-mono text-small">has(steps.get_device.output) &amp;&amp; steps.get_device.output.site_name != &quot;&quot;</p>
        <p className="flex items-center gap-2 text-small text-muted">
          Press <kbd className="rounded-sm border border-line-strong px-1 font-mono text-meta">/</kbd> or{" "}
          <kbd className="rounded-sm border border-line-strong px-1 font-mono text-meta">⌘K</kbd>
        </p>
      </div>
    </Section>
  );
}

const BTN = "inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 text-body font-medium";
const FOCUS = "outline-2 outline-offset-2 outline-focus";
const DISABLED = "border-disabled-line bg-disabled-bg text-disabled-ink";
const LABELS: Record<ButtonVariant, string> = {
  primary: "Publish v3",
  secondary: "Cancel",
  simulate: "Simulate step",
  "live-outline": "Run step against Mist…",
  live: "Restart 1 device",
  "danger-outline": "Delete",
  danger: "Delete workflow",
};

function look(variant: ButtonVariant, state: (typeof BUTTON_STATE_NAMES)[number]): string {
  const { fg, bg, border } = BUTTON_STATES[variant][state];
  return `${FG[fg]} ${BG[bg]} ${BORDER[border]}`;
}

function States() {
  const field = "min-h-10 w-56 rounded-lg border bg-surface px-3 text-body";
  return (
    <Section title="Controls and states">
      <div className="grid grid-cols-[auto_repeat(5,max-content)] items-center gap-x-4 gap-y-2 rounded-lg border border-line bg-surface p-4">
        {["", "default", "hover", "pressed", "focus", "disabled"].map((h) => (
          <span key={h} className="text-meta text-muted">{h}</span>
        ))}
        {(Object.keys(BUTTON_STATES) as ButtonVariant[]).map((v) => (
          <Row key={v} label={v}>
            {BUTTON_STATE_NAMES.map((state) => (
              <span key={state} data-variant={v} data-state={state} className={`${BTN} ${look(v, state)}`}>
                {LABELS[v]}
              </span>
            ))}
            <span data-variant={v} data-state="focus" className={`${BTN} ${look(v, "default")} ${FOCUS}`}>
              {LABELS[v]}
            </span>
            <span data-variant={v} data-state="disabled" className={`${BTN} ${DISABLED}`}>
              {LABELS[v]}
            </span>
          </Row>
        ))}
      </div>
      <div className="grid grid-cols-4 gap-4 rounded-lg border border-line bg-surface p-4">
        <Field label="Name" hint="default">
          <span className={`${field} flex items-center border-line-control`}>Acme Prod · EU</span>
        </Field>
        <Field label="Name" hint="focus">
          <span className={`${field} flex items-center border-line-control ${FOCUS}`}>Acme Prod · EU</span>
        </Field>
        <Field label="Organization ID" hint="error" error="Enter the 36-character UUID from Mist.">
          <span className={`${field} flex items-center border-danger`}>5c1e0a2f</span>
        </Field>
        <Field label="Name" hint="disabled">
          <span data-sample="disabled" className={`${field} flex items-center ${DISABLED}`}>Acme Prod · EU</span>
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-6 rounded-lg border border-line bg-surface p-4">
        <Check checked={false} label="Unchecked" />
        <Check checked label="Checked" />
        <Toggle on={false} label="Disabled workflow" />
        <Toggle on label="Enabled workflow" />
        <div className="flex border-b border-line">
          <span className="border-b-2 border-accent px-2.5 py-2 font-semibold">Setup</span>
          <span className="px-2.5 py-2 text-muted">Options</span>
          <span className="px-2.5 py-2 text-muted">Test</span>
        </div>
        <span className="rounded-md bg-accent-soft px-3 py-2 font-medium text-accent-ink">Selected item</span>
      </div>
    </Section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <span className="font-mono text-caption text-muted">{label}</span>
      {children}
    </>
  );
}

function Field({ label, hint, error, children }: { label: string; hint: string; error?: string; children: ReactNode }) {
  return (
    <span className="flex flex-col gap-1.5">
      <span className="text-small font-semibold">
        {label} <span className="font-normal text-muted">· {hint}</span>
      </span>
      {children}
      {error && <span className="text-small text-danger">{error}</span>}
    </span>
  );
}

function Check({ checked, label }: { checked: boolean; label: string }) {
  return (
    <span className="flex items-center gap-2 text-body">
      <span
        className={`flex h-4 w-4 items-center justify-center rounded-sm border text-caption ${checked ? "border-accent bg-accent text-on-accent" : "border-line-control bg-surface"}`}
      >
        {checked ? "✓" : ""}
      </span>
      {label}
    </span>
  );
}

function Toggle({ on, label }: { on: boolean; label: string }) {
  return (
    <span className="flex items-center gap-2 text-body">
      <span className={`relative h-5 w-[34px] rounded-pill ${on ? "bg-accent" : "bg-line-control"}`}>
        <span className={`absolute top-0.5 h-4 w-4 rounded-pill bg-surface ${on ? "left-4" : "left-0.5"}`} />
      </span>
      {label}
    </span>
  );
}

const CHIP = "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-small";

function Meaning() {
  return (
    <Section title="Meaning">
      <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
        <div className="flex flex-wrap gap-2">
          <span className={`${CHIP} border-line-strong text-muted`}>Queued</span>
          <span className={`${CHIP} border-accent text-accent-ink`}>Running</span>
          <span className={`${CHIP} border-ok text-ok`}>Succeeded</span>
          <span className={`${CHIP} border-danger text-danger`}>Failed</span>
          <span className={`${CHIP} border-line-strong text-muted`}>Cancelled</span>
          <span className={`${CHIP} border-warn-line bg-warn-bg text-warn-ink`}>Outcome unknown</span>
          <span className={`${CHIP} border-line-strong text-ink`}>◷ Awaiting approval</span>
          <span className={`${CHIP} border-live bg-live-bg text-live`}>Live</span>
          <span className={`${CHIP} hatch-sim border-sim bg-sim-bg text-sim`}>Simulated</span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-caption">
          <span className="text-meta text-muted">Data origin</span>
          <span className="rounded-sm bg-live-bg px-1.5 py-px text-live">real input</span>
          <span className="rounded-sm border border-line-strong px-1.5 py-px text-muted">evaluated</span>
          <span className="hatch-sim rounded-sm bg-sim-bg px-1.5 py-px text-sim">fixture</span>
          <span className="hatch-sim rounded-sm bg-sim-bg px-1.5 py-px text-sim">not sent</span>
          <span className="rounded-sm border border-dashed border-line-strong px-1.5 py-px text-muted">skipped</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-body">
          <span>AP</span>
          <span className="rounded-pill border border-accent bg-accent-soft px-2 font-mono text-small text-accent-ink">trigger › device_mac</span>
          <span>at site</span>
          <span className="rounded-pill border border-accent bg-accent-soft px-2 font-mono text-small text-accent-ink">get_device › site_name</span>
          <span>went offline</span>
          <span className="rounded-pill border border-dashed border-warn-line bg-warn-bg px-2 font-mono text-small text-warn-ink">
            get_device › last_seen ?<span className="sr-only"> (conditional)</span>
          </span>
          <span className="rounded-pill border border-line-strong px-2 font-mono text-small">
            severity <span className="text-muted">enum</span>
          </span>
        </div>
        <div className="flex flex-col gap-2">
          <div className="rounded-lg border border-live bg-live-bg px-3 py-2 text-small text-live">
            <strong>Live run.</strong> Calls were made to Mist and Slack. Inputs and outputs are redacted per node schema.
          </div>
          <div className="hatch-sim rounded-lg border border-sim bg-sim-bg px-3 py-2 text-small text-sim">
            <strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.
          </div>
          <div className="rounded-lg border border-danger bg-danger-bg px-3 py-2 text-small text-ink">
            <strong className="text-danger">channel_not_found</strong> Slack returned channel_not_found. 3 attempts. Side effect: nothing posted.
          </div>
          <div className="rounded-lg border border-warn-line bg-warn-bg px-3 py-2 text-small text-warn-ink">
            <strong>Needs a grant before publish.</strong> servicenow.incident.create has no service grant.
          </div>
        </div>
        <div className="flex items-center gap-2 text-small">
          <span className="text-muted">Redacted preview</span>
          <code className="rounded-sm border border-line bg-surface-2 px-1.5 font-mono text-meta">
            &quot;token&quot;: <span className="rounded-sm border border-line-strong px-1 text-muted">redacted</span>
          </code>
        </div>
      </div>
    </Section>
  );
}

function Node({ code, title, sub, state }: { code: string; title: string; sub: string; state?: "selected" | "failed" | "simulated" }) {
  const ring = state === "selected" ? "outline-2 outline-accent" : state === "failed" ? "outline-2 outline-danger" : "";
  return (
    <div className={`flex w-[260px] items-center gap-3 rounded-lg border px-3.5 py-3 shadow-node ${ring} ${state === "simulated" ? "border-sim bg-sim-bg" : "border-line-strong bg-surface"}`}>
      <span className="w-10 shrink-0 font-mono text-caption font-semibold text-accent-ink">{code}</span>
      <span className="flex min-w-0 grow flex-col">
        <span className="font-semibold">{title}</span>
        <span className="text-small text-muted">{sub}</span>
      </span>
      {state === "failed" && <span className="rounded-sm bg-danger-bg px-1.5 text-caption text-danger">failed</span>}
      {state === "simulated" && <span className="hatch-sim rounded-sm border border-sim bg-sim-bg px-1.5 text-caption text-sim">fixture</span>}
    </div>
  );
}

function Canvas({ theme }: { theme: Theme }) {
  return (
    <Section title="Canvas">
      <div className="relative overflow-hidden rounded-lg border border-line bg-ground">
        <svg className="absolute inset-0 h-full w-full" aria-hidden="true">
          <defs>
            <pattern id={`dots-${theme}`} width="20" height="20" patternUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="1" className="fill-line-strong" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill={`url(#dots-${theme})`} />
        </svg>
        <div className="relative flex flex-col items-center gap-0 py-6">
          <Node code="HOOK" title="Mist webhook · device events" sub="AP_DISCONNECTED · all sites" />
          <Edge />
          <Node code="GET" title="get_device" sub="Mist · Device · Get" state="selected" />
          <Edge />
          <Node code="AGENT" title="triage_ap" sub="AI agent · 2 tools" state="simulated" />
          <Edge />
          <Node code="MSG" title="notify_noc" sub="3 attempts · channel_not_found" state="failed" />
        </div>
      </div>
    </Section>
  );
}

function Edge() {
  return (
    <span className="relative flex h-12 w-6 justify-center">
      <span className="h-full w-[1.5px] bg-edge" />
      <span className="absolute top-3 flex h-6 w-6 items-center justify-center rounded-pill border border-line-control bg-surface text-small text-muted">
        ＋
      </span>
    </span>
  );
}

function Rail() {
  const item = "flex items-center gap-2.5 rounded-md px-3 py-2 text-body";
  return (
    <Section title="Rail">
      <div className="flex gap-4">
        <nav data-surface="rail" className="flex w-[224px] flex-col gap-0.5 rounded-lg bg-rail p-3">
          <span className="px-2 pt-2 pb-5">
            <Wordmark />
          </span>
          <span className={`${item} text-rail-ink`}>Home · default</span>
          <span className={`${item} bg-rail-line text-rail-ink`}>Runs · hover</span>
          <span className={`${item} bg-rail-active font-semibold text-rail-ink-strong`} aria-current="page">
            Workflows · current
          </span>
          <span className={`${item} text-rail-ink outline-2 outline-offset-2 outline-focus-rail`}>Connections · focus</span>
          <span className={`${item} text-rail-ink`}>Settings</span>
        </nav>
        <nav data-surface="rail" className="flex w-[60px] flex-col items-center gap-1.5 rounded-lg bg-rail py-3">
          <span className="mb-3">
            <Mark />
          </span>
          <span className="h-10 w-10 rounded-lg bg-rail-active" />
          <span className="h-10 w-10 rounded-lg border border-rail-line" />
        </nav>
      </div>
    </Section>
  );
}

function Shape() {
  return (
    <Section title="Shape and elevation">
      <div className="flex flex-wrap items-end gap-4">
        {[
          ["rounded-sm", "sm 4"],
          ["rounded-md", "md 6"],
          ["rounded-lg", "default 8"],
          ["rounded-dialog", "dialog 12"],
          ["rounded-pill", "pill"],
        ].map(([cls, label]) => (
          <span key={label} className={`flex h-14 w-24 items-center justify-center border border-line-strong bg-surface text-meta ${cls}`}>
            {label}
          </span>
        ))}
        <span className="flex h-14 w-32 items-center justify-center rounded-lg border border-line-strong bg-surface text-meta shadow-node">
          shadow-node
        </span>
        <span className="relative flex h-28 w-64 items-center justify-center rounded-lg bg-overlay">
          <span className="rounded-dialog border border-line bg-surface px-4 py-3 text-small shadow-dialog">Dialog · shadow-dialog</span>
        </span>
      </div>
    </Section>
  );
}

function Panel({ theme }: { theme: Theme }) {
  const ref = useRef<HTMLElement>(null);
  const get = useTokens(ref);
  return (
    <section ref={ref} data-theme={theme} className="flex flex-col gap-8 bg-ground p-8 text-ink">
      <h1 className="text-h1 font-semibold">{theme === "light" ? "Light theme" : "Dark theme"}</h1>
      <Swatches get={get} />
      <Pairs get={get} />
      <Type />
      <States />
      <Meaning />
      <div className="grid grid-cols-2 gap-8">
        <Canvas theme={theme} />
        <Rail />
      </div>
      <Shape />
    </section>
  );
}

export function Specimen() {
  return (
    <main>
      <Panel theme="light" />
      <Panel theme="dark" />
    </main>
  );
}
