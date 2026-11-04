import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The customer app is served under /support/ on the Cosmic Resolve deployment.
// Asset URLs are generated under /support/assets/... so static files resolve through the same prefix.
// API calls use absolute /api/... paths, which the backend serves through its /api prefix handling.
// Local development: the backend runs on port 8000 (uvicorn api:app --port 8000, from backend/).
const apiProxy = {
  "/api": {
    target: "http://localhost:8000",
    changeOrigin: true,
  },
};

export default defineConfig({
  base: "/support/",
  // The build lands in dist/support/, so the service's output contains support/index.html and support/assets/*.
  // A request for /support/assets/x.js then matches a real file at that path, whether or not Vercel strips the
  // prefix before static serving. A prefix rewrite alone was not reliable here (see the backend /api transform).
  build: {
    outDir: "dist/support",
    emptyOutDir: true,
  },
  plugins: [react()],
  server: { port: 5174, proxy: apiProxy },
  preview: { port: 5174, proxy: apiProxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
});
