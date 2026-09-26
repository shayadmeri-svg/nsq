import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the backend (default :8001). In production the
// gateway serves the SPA and the API from one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.API_URL ?? "http://localhost:8001", changeOrigin: false },
    },
  },
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: { charts: ["recharts"], motion: ["motion"], react: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"] },
      },
    },
  },
});
