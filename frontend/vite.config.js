import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("@sparkjsdev")) return "spark";
          if (id.includes("three/examples") || id.includes("three-stdlib")) return "three-extras";
          if (id.includes("/three/")) return "three";
          if (id.includes("@react-three")) return "r3f";
        },
      },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.js"] },
});
