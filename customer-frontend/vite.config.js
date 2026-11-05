import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The customer page mounts the existing Cosmo voice UI instead of keeping a copy of it. That code lives in
// frontend/src/voice and is imported through this alias. Two things make that safe:
//  - resolve.dedupe makes every "react" import, including the ones inside the shared files (which sit next to the
//    internal app's own node_modules), resolve to THIS app's single copy. Without it the hooks would run against a second
//    React and fail with "Invalid hook call". The production build and a browser test check this.
//  - server.fs.allow lets the dev server read the shared folder, which is outside this app's root.
const here = path.dirname(fileURLToPath(import.meta.url));
const voiceSource = path.resolve(here, "../frontend/src/voice");

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
  resolve: {
    alias: { "@cosmo-voice": voiceSource },
    dedupe: ["react", "react-dom"],
  },
  server: { port: 5174, proxy: apiProxy, fs: { allow: [path.resolve(here, "..")] } },
  preview: { port: 5174, proxy: apiProxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
});
