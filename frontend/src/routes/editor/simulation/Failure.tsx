// SPDX-License-Identifier: Apache-2.0
// A simulated step that failed (4d-1c; the simulation design §7.7; the Refusals and TestResult boards): its code and
// message as the server wrote them, its attempts (its retries said when it used them all), and that nothing was sent.
import { field } from "./results";

const attempts = (n: number, max: number | null) => (n === 1 ? "1 attempt." : n === max ? `${n} attempts, the configured retries.` : `${n} attempts.`);

/** `final`: a step's final attempt (the run API's step); `max`: its attempts, its own or its type's. */
export function Failure({ final, max }: { final: unknown; max: number | null }) {
  const error = field(final, "error");
  const code = field(error, "code");
  if (field(final, "status") !== "failed" || typeof code !== "string") return null;
  const message = field(error, "message");
  const attempt = field(final, "attempt");
  return (
    <p className="basis-full text-small text-muted">
      <span className="font-mono text-ink">{code}</span>
      {` ${typeof message === "string" ? message : ""} ${attempts(typeof attempt === "number" ? attempt : 1, max)} Nothing was sent.`}
    </p>
  );
}
