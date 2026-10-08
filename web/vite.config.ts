import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In production FastAPI serves the built files and /api from one origin.
// In development, Vite proxies /api (including the WebSocket feed) to the local API.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", ws: true, changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
