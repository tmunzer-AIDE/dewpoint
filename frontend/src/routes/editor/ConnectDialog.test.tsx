// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { ConnectDialog } from "./ConnectDialog";

const A = "5f0c6e2a-2b2b-4e2b-9c2b-2b2b2b2b2b2b";
const B = "6a1d7f3b-3c3c-4f3c-8d3c-3c3c3c3c3c3c";

it("names the step it connects from whatever way the draft spells its id (M15)", () => {
  // The port arrives canonical (from the keyboard model and the port items); the draft spells the step in capitals.
  const doc: GraphDoc = {
    graph_format: 1,
    nodes: [
      { id: A.toUpperCase(), key: "if", type: "flow.if@1", config: {} },
      { id: B, key: "stop", type: "flow.stop@1", config: {} },
    ],
    edges: [],
  };
  render(<ConnectDialog doc={doc} types={new Map()} from={{ node: A, port: "true" }} onConnect={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Connect if (true) to");
});
