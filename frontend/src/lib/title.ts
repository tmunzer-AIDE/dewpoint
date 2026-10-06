// SPDX-License-Identifier: Apache-2.0
import { useEffect } from "react";

/** Names the page in the browser's title and tab (WCAG 2.4.2): each screen of the app says which it is. */
export function useDocumentTitle(name: string): void {
  useEffect(() => {
    document.title = `${name} · Dewpoint`;
  }, [name]);
}
