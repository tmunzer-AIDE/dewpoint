// SPDX-License-Identifier: Apache-2.0
// The rail's 16 px stroke icons, from the design (screen 1a); Connections is drawn in the same hand. Decoration only:
// every one sits beside its text label.
import type { ReactNode } from "react";

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      {children}
    </svg>
  );
}

export const WorkflowsIcon = () => (
  <Icon>
    <rect x="2" y="2" width="5" height="4" rx="1" />
    <rect x="9" y="10" width="5" height="4" rx="1" />
    <path d="M4.5 6v3h7v1" />
  </Icon>
);

export const RunsIcon = () => (
  <Icon>
    <path d="M1.5 8h3l2-4 3 8 2-4h3" />
  </Icon>
);

export const ConnectionsIcon = () => (
  <Icon>
    <path d="M6.5 9.5 9.5 6.5M7 4.5l1-1a2.5 2.5 0 0 1 3.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 0 1 4.5 9l1-1" />
  </Icon>
);

export const SettingsIcon = () => (
  <Icon>
    <circle cx="8" cy="8" r="2" />
    <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" />
  </Icon>
);

/** A row's menu: three square dots, drawn rather than typed (three middle dots merge into a dash at 13 px). */
export const MoreIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
    <rect x="2" y="7" width="2.5" height="2.5" rx="0.5" />
    <rect x="6.75" y="7" width="2.5" height="2.5" rx="0.5" />
    <rect x="11.5" y="7" width="2.5" height="2.5" rx="0.5" />
  </svg>
);
