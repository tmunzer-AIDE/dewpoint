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
