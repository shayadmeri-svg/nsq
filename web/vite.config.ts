import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Dev server proxies /api to the manufacturer_api FastAPI service (default
// :8001). In production the nginx gateway makes the frontend same-origin.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.MANUFACTURER_API_URL ?? "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
});