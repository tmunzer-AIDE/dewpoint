// SPDX-License-Identifier: Apache-2.0
// ai-tells-allow: eyebrow (the wordmark's tracked "for Juniper Mist" is the one exception, outline §6)

/** The mark, variant B "Condensation": two circles meeting, vapour becoming a drop (D7). */
export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <circle cx="13" cy="18" r="10" className="fill-accent" />
      <circle cx="22.5" cy="11.5" r="6" strokeWidth="2" className="fill-brand stroke-rail" />
    </svg>
  );
}

/** The mark with the product's name, for the rail. */
export function Wordmark() {
  return (
    <span className="flex items-center gap-2.5">
      <Mark />
      <span className="flex flex-col gap-1.5">
        <span className="font-display text-[17px] leading-none font-semibold tracking-[-0.01em] text-rail-ink-strong">
          Dewpoint
        </span>
        <span className="font-mono text-[10px] leading-none font-medium tracking-[0.12em] text-rail-dim uppercase">
          for Juniper Mist
        </span>
      </span>
    </span>
  );
}
