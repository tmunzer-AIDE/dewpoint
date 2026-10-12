// SPDX-License-Identifier: Apache-2.0
// Testing Library unmounts after each test only with vitest's globals, which this project leaves off.
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);

// jsdom lacks what the browser gives the palette: a modal <dialog>, ResizeObserver and scrollIntoView. These stand-ins
// only open and close; the browser gate checks the real ones.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    if (!this.hasAttribute("open")) return;
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
if (!("scrollIntoView" in Element.prototype)) {
  Object.defineProperty(Element.prototype, "scrollIntoView", { value: () => undefined, configurable: true, writable: true });
}
// The router restores scroll on navigation; jsdom only reports that it has no scrolling.
window.scrollTo = () => undefined;
// Node 26's own (experimental) localStorage global wins over jsdom's and is undefined without a storage file: an
// in-memory Storage stands in, as a browser's would.
if (typeof globalThis.localStorage?.getItem !== "function") {
  const items = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return items.size;
    },
    key: (i) => [...items.keys()][i] ?? null,
    getItem: (k) => items.get(k) ?? null,
    setItem: (k, v) => void items.set(k, String(v)),
    removeItem: (k) => void items.delete(k),
    clear: () => items.clear(),
  };
  Object.defineProperty(globalThis, "localStorage", { value: storage, configurable: true });
}
// jsdom 25's Blob (and so File) has no text(), which every browser gives: read through its FileReader instead, so a
// file the person picks reads as it would in a browser.
if (typeof Blob.prototype.text !== "function") {
  Object.defineProperty(Blob.prototype, "text", {
    configurable: true,
    writable: true,
    value(this: Blob): Promise<string> {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = () => reject(reader.error ?? new Error("the file couldn't be read"));
        reader.readAsText(this);
      });
    },
  });
}
