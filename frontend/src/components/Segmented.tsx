// SPDX-License-Identifier: Apache-2.0

/** A choice among a few views, each with its count: buttons in a named group, the chosen one pressed (1a's filter
 * chips, as a segmented control: no pills, outline §6). */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string; count: number }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex flex-wrap overflow-hidden rounded-lg border border-line-strong">
      {options.map((o, i) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`min-h-9 px-3 text-small ${i > 0 ? "border-l border-line-strong" : ""} ${
            o.value === value ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink hover:bg-surface-hover"
          }`}
        >
          {o.label} <span className="font-mono text-meta">{o.count}</span>
        </button>
      ))}
    </div>
  );
}
