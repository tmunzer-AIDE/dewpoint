// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";

const sources = import.meta.glob<string>(["/src/**/*.tsx", "!/src/**/*.test.tsx"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** A `pattern` attribute is compiled with the `v` flag (HTML spec); one that doesn't compile is silently ignored, and
 * the field then accepts anything. In `v` mode a class's literal `-` must be escaped. */
it("every input pattern compiles as the browser compiles it", () => {
  const broken = Object.entries(sources).flatMap(([path, text]) =>
    [...text.matchAll(/\bpattern="([^"]*)"/g)].flatMap(([, p]) => {
      try {
        new RegExp(`^(?:${p})$`, "v");
        return [];
      } catch {
        return [`${path}: ${p}`];
      }
    }),
  );
  expect(broken).toEqual([]);
});
