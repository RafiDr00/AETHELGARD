import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react": ["react", "react-dom"],
          "vendor-lucide": ["lucide-react"],
        },
      },
    },
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        // EventSource (SSE) requires ws: false — SSE is plain HTTP, not WebSocket.
        ws: false,
      },
      "/health": { target: "http://localhost:8080", changeOrigin: true },
      "/ready": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        ws: false,
      },
      "/health": { target: "http://localhost:8080", changeOrigin: true },
      "/ready": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
});
