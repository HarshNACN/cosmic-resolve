import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

import { fetchSupportedLanguageCodes } from "./i18n/supportedLanguages.js";

// The page renders at once with every language it has text for, then narrows the selector to the languages the running
// voice system reports. The first render is not delayed, and the narrowing keeps all of the page's state.
const root = createRoot(document.getElementById("root"));
root.render(<App />);
fetchSupportedLanguageCodes().then((codes) => {
  if (codes) root.render(<App supportedLanguages={codes} />);
});
