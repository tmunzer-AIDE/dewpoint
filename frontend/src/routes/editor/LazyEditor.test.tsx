// SPDX-License-Identifier: Apache-2.0
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { LazyEditor, type EditorModule } from "./LazyEditor";

const Page = ({ workflowId }: { tenantId: string; workflowId: string }) => <p>editor of {workflowId}</p>;

/** A load of the editor's code that answers when the test says. */
function held() {
  let answer!: (ok: boolean) => void;
  const load = vi.fn(
    () => new Promise<EditorModule>((resolve, reject) => (answer = (ok) => (ok ? resolve({ EditorPage: Page }) : reject(new Error("chunk")))))
  );
  return { load, answer: (ok: boolean) => act(async () => { answer(ok); await Promise.resolve(); }) };
}

it("says the editor is loading, then shows it", async () => {
  const { load, answer } = held();
  render(<LazyEditor tenantId="t1" workflowId="w1" load={load} />);
  expect(screen.getByRole("status").textContent).toBe("Loading the editor…");
  await answer(true);
  expect(await screen.findByText("editor of w1")).toBeTruthy();
});

it("says when the editor's code can't be loaded, and tries again when asked", async () => {
  const first = held();
  const second = held();
  const load = vi.fn().mockImplementationOnce(first.load).mockImplementationOnce(second.load);
  render(<LazyEditor tenantId="t1" workflowId="w1" load={load} />);
  await first.answer(false);
  expect((await screen.findByRole("alert")).textContent).toContain("The editor couldn't be loaded");
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(screen.getByRole("status").textContent).toBe("Loading the editor…");
  await second.answer(true);
  expect(await screen.findByText("editor of w1")).toBeTruthy();
  expect(load).toHaveBeenCalledTimes(2);
});
