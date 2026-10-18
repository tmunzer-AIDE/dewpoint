// SPDX-License-Identifier: Apache-2.0
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { LazyPage } from "./LazyPage";

const Page = ({ tenantId }: { tenantId: string }) => <p>runs of {tenantId}</p>;

/** A load of a page's code that answers when the test says. */
function held() {
  let answer!: (ok: boolean) => void;
  const load = vi.fn(() => new Promise<typeof Page>((resolve, reject) => (answer = (ok) => (ok ? resolve(Page) : reject(new Error("chunk"))))));
  return { load, answer: (ok: boolean) => act(async () => { answer(ok); await Promise.resolve(); }) };
}

it("says a page's code is loading, then shows the page", async () => {
  const { load, answer } = held();
  render(<LazyPage load={load} what="the runs" props={{ tenantId: "t1" }} />);
  expect(screen.getByRole("status").textContent).toBe("Loading the runs…");
  await answer(true);
  expect(await screen.findByText("runs of t1")).toBeTruthy();
});

it("says when a page's code can't be loaded, and tries again when asked", async () => {
  const first = held();
  const second = held();
  const load = vi.fn().mockImplementationOnce(first.load).mockImplementationOnce(second.load);
  render(<LazyPage load={load} what="the runs" props={{ tenantId: "t1" }} />);
  await first.answer(false);
  expect((await screen.findByRole("alert")).textContent).toContain("The runs couldn't be loaded. Check your connection, then try again.");
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await second.answer(true);
  expect(await screen.findByText("runs of t1")).toBeTruthy();
  expect(load).toHaveBeenCalledTimes(2);
});
