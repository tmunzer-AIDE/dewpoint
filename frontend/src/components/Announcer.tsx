// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";
import { onAnnounce } from "../lib/announce";

/** The shell's polite live region. It empties before each message, so the same words twice are heard twice. */
export function Announcer() {
  const [message, setMessage] = useState("");
  useEffect(
    () =>
      onAnnounce((m) => {
        setMessage("");
        window.setTimeout(() => setMessage(m), 30);
      }),
    [],
  );
  return (
    <div role="status" aria-live="polite" className="sr-only">
      {message}
    </div>
  );
}
