import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The landing page is the front door at "/". It is a separate app from the case workbench (/internal/) and the
// customer portal (/support/). Deployed, Vercel routes the three paths (see vercel.json). Locally this dev server
// is the single address you open (http://localhost:5173) and it forwards the other two paths, plus the API, so the
// browser only ever sees one origin. ws keeps hot reload working for the forwarded apps.
const forward = (target) => ({ target, changeOrigin: true, ws: true });

const proxy = {
  "/api": { target: "http://localhost:8000", changeOrigin: true },
  "/support": forward("http://localhost:5174"),
  "/internal": forward("http://localhost:5175"),
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { port: 5173, proxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
});
