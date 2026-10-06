// SPDX-License-Identifier: Apache-2.0

/** Says a list couldn't be loaded, in the list's place: an empty list would read as "none". */
export function LoadError({ what }: { what: string }) {
  return <p role="alert" className="text-body text-danger">{what} couldn&apos;t be loaded. Reload the page to try again.</p>;
}
