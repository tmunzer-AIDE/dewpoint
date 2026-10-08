// SPDX-License-Identifier: Apache-2.0

/** A file name from a workflow's name: lowercase words joined by dashes, then `suffix`. */
export function fileName(name: string, suffix: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${slug || "workflow"}${suffix}`;
}

/** Hands the person a JSON file, saved by the browser: the data never goes into a URL (a blob's URL names it). */
export function downloadJson(name: string, data: unknown): void {
  const url = URL.createObjectURL(new Blob([`${JSON.stringify(data, null, 2)}\n`], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
