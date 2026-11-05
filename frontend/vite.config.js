import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The case workbench is served under /internal/ on the Cosmic Resolve site; the landing page owns "/".
// Asset URLs are generated under /internal/assets/... and the build lands in dist/internal/, so a request for
// /internal/assets/x.js matches a real file at that path whether or not Vercel strips the prefix. This is the same
// arrangement customer-frontend uses for /support/.
//
// Local development: open http://localhost:5173 (the landing dev server). It forwards /internal here (port 5175)
// and /api to the backend, so the browser sees one origin. The proxy below only matters when this server is
// opened directly. The backend must be running on port 8000 (uvicorn api:app --port 8000, from backend/).
const apiProxy = {
  "/api": {
    target: "http://localhost:8000",
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  base: "/internal/",
  build: {
    outDir: "dist/internal",
    emptyOutDir: true,
  },
  plugins: [react()],
  server: { port: 5175, proxy: apiProxy },
  preview: { port: 5175, proxy: apiProxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
});
