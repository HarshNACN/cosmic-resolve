import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The browser talks only to the Cosmic Resolve backend, through this same-origin proxy.
// The backend must be running on port 8000 (uvicorn api:app --port 8000, from backend/).
const apiProxy = {
  "/api": {
    target: "http://localhost:8000",
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: apiProxy },
  preview: { proxy: apiProxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
});
