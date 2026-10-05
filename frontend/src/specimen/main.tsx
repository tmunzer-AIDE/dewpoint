// SPDX-License-Identifier: Apache-2.0
// The token specimen's entry: `pnpm dev`, then /specimen.html. The production build has index.html as its only input.
import "@fontsource/instrument-sans/latin-400.css";
import "@fontsource/instrument-sans/latin-500.css";
import "@fontsource/instrument-sans/latin-600.css";
import "@fontsource/schibsted-grotesk/latin-600.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "@fontsource/jetbrains-mono/latin-600.css";
import "../styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Specimen } from "./Specimen";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <Specimen />
    </StrictMode>,
  );
}
