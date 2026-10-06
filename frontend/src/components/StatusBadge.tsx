// SPDX-License-Identifier: Apache-2.0
const LABELS: Record<string, string> = {
  invalid_token: "invalid token",
  no_org_access: "no access to this org",
  unreachable: "Mist unreachable",
  unexpected_status: "unexpected response",
  secret_unreadable: "secret unreadable",
};

export function StatusBadge({ status, detail, privilege }: { status: string; detail: string; privilege: string | null }) {
  if (status === "ok") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-ok px-2 py-0.5 text-small text-ok">
        Verified{privilege ? ` · ${privilege}` : ""}
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-danger px-2 py-0.5 text-small text-danger">
        Failed: {LABELS[detail] ?? detail}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-md border border-line-strong px-2 py-0.5 text-small text-muted">
      Not verified
    </span>
  );
}
