import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 8080,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
      "/docs": { target: "http://localhost:8000", changeOrigin: true },
      "/redoc": { target: "http://localhost:8000", changeOrigin: true },
      "/openapi.json": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
