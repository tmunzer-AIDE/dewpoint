// SPDX-License-Identifier: Apache-2.0
// When something happened, in the person's own zone, with the full date and zone on hover (the owner's answer 8).
import { when, whenFull } from "../lib/when";

export function When({ iso }: { iso: string }) {
  return (
    <time dateTime={iso} title={whenFull(iso)}>
      {when(iso)}
    </time>
  );
}
