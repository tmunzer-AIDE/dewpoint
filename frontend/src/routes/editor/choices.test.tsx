// SPDX-License-Identifier: Apache-2.0
import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ChoiceList, useScopedChoices, type Option } from "./choices";

const SITES: Option[] = [{ value: "8a27c4d0-5e1f-4b6a-9c2d-3f4e5a6b7c8d", label: "Lyon DC" }, { value: "s2", label: "Lyon store 4" }];

afterEach(() => vi.restoreAllMocks());

it("takes focus when shown, as the drawer's list does (ruling 338)", () => {
  render(<ChoiceList label="Site" options={SITES} onPick={vi.fn()} onClose={vi.fn()} />);
  expect(document.activeElement).toBe(screen.getByRole("listbox", { name: "Choices for Site" }));
});

it("is shown without taking focus in a start form, under the id the field controls (the 4f-3 design §5.1)", () => {
  render(<ChoiceList label="Site" options={SITES} onPick={vi.fn()} onClose={vi.fn()} id="site-list" focusOnShow={false} />);
  const list = screen.getByRole("listbox", { name: "Choices for Site" });
  expect(document.activeElement).not.toBe(list);
  expect(list.id).toBe("site-list");
});

it("makes a start form's rows 44 px below 640 px, the name over the id; the drawer's rows stay as they are", () => {
  const { unmount } = render(<ChoiceList label="Site" options={SITES} onPick={vi.fn()} onClose={vi.fn()} tall />);
  const row = screen.getByRole("option", { name: /^Lyon DC/ });
  expect(row.className).toContain("max-sm:min-h-[44px]");
  expect(row.className).toContain("max-sm:flex-col");
  expect(row.textContent).toBe("Lyon DC8a27c4d0…");
  unmount();
  render(<ChoiceList label="Site" options={SITES} onPick={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole("option", { name: /^Lyon DC/ }).className).not.toContain("max-sm:");
});

it("closes cleanly where scrollIntoView answers a promise (Chromium 153): its effect returns no cleanup", () => {
  const scroll = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => Promise.resolve() as unknown as undefined);
  const { unmount } = render(<ChoiceList label="Site" options={SITES} onPick={vi.fn()} onClose={vi.fn()} />);
  expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
  expect(() => unmount()).not.toThrow();
});

it("moves with Up and Down, picks with Enter and closes with Escape, never past the list", async () => {
  const onPick = vi.fn();
  const onClose = vi.fn();
  const outer = vi.fn();
  render(
    <div onKeyDown={outer}>
      <ChoiceList label="Site" options={SITES} onPick={onPick} onClose={onClose} />
    </div>,
  );
  await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
  expect(onPick).toHaveBeenCalledWith(SITES[1]);
  await userEvent.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalledOnce();
  expect(outer).not.toHaveBeenCalled();
});

it("keeps an answer for the scope it was asked in, with the query it answered", async () => {
  const read = vi.fn(() => Promise.resolve(SITES));
  const { result } = renderHook(() => useScopedChoices("a", read, () => "failed"));
  await act(() => result.current.load("ly".repeat(150)));
  expect(read).toHaveBeenCalledWith("ly".repeat(100)); // at most 200 characters, as the API takes
  expect(result.current.shown).toEqual({ status: "done", options: SITES, query: "ly".repeat(100) });
});

it("ignores an answer for an older scope, and a scope come back is a new era (ruling 109)", async () => {
  let settle: (o: Option[]) => void = () => undefined;
  const read = vi.fn(() => new Promise<Option[]>((resolve) => (settle = resolve)));
  const { result, rerender } = renderHook(({ scope }) => useScopedChoices(scope, read, () => "failed"), { initialProps: { scope: "a" } });
  let loading: Promise<void> = Promise.resolve();
  act(() => void (loading = result.current.load("")));
  expect(result.current.shown).toEqual({ status: "loading" });
  rerender({ scope: "b" });
  expect(result.current.shown).toEqual({ status: "idle" });
  rerender({ scope: "a" });
  await act(async () => {
    settle(SITES);
    await loading;
  });
  expect(result.current.shown).toEqual({ status: "idle" });
});

it("drops an answer on its way once the list is closed: a later read still answers", async () => {
  let settle: (o: Option[]) => void = () => undefined;
  const read = vi.fn(() => new Promise<Option[]>((resolve) => (settle = resolve)));
  const { result } = renderHook(() => useScopedChoices("a", read, () => "failed"));
  let loading: Promise<void> = Promise.resolve();
  act(() => void (loading = result.current.load("ly")));
  act(() => result.current.close());
  await act(async () => {
    settle(SITES);
    await loading;
  });
  expect(result.current.shown).toEqual({ status: "idle" });
  act(() => void (loading = result.current.load("ly")));
  await act(async () => {
    settle(SITES);
    await loading;
  });
  expect(result.current.shown).toEqual({ status: "done", options: SITES, query: "ly" });
});

it("says why a read failed, in the caller's words", async () => {
  const { result } = renderHook(() => useScopedChoices("a", () => Promise.reject(new Error("503")), (e) => `why: ${(e as Error).message}`));
  await act(() => result.current.load(""));
  expect(result.current.shown).toEqual({ status: "failed", why: "why: 503" });
});
