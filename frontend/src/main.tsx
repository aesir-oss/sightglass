import "@fontsource/familjen-grotesk/500.css";
import "@fontsource/familjen-grotesk/700.css";
import "@fontsource-variable/source-sans-3";
import "@fontsource/ibm-plex-mono/400.css";
import "./theme.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

const root = document.getElementById("root");
if (!root) {
  throw new Error("missing #root element");
}
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
