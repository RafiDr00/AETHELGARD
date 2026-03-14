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
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react": ["react", "react-dom"],
          "vendor-query": ["@tanstack/react-query"],
          "vendor-motion": ["framer-motion"],
          "vendor-charts": ["recharts"],
          "vendor-three": ["three", "@react-three/fiber", "@react-three/drei"],
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
        ws: true,
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
        ws: true,
      },
      "/health": { target: "http://localhost:8080", changeOrigin: true },
      "/ready": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
});
