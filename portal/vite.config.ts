/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const API_TARGET = process.env.VITE_API_PROXY || "http://localhost:8000";

/** El portal siempre habla con la API por el mismo origen (dev y preview). */
const proxy = {
  "/api": { target: API_TARGET, changeOrigin: true },
  "/health": { target: API_TARGET, changeOrigin: true },
  "/docs": { target: API_TARGET, changeOrigin: true },
  "/redoc": { target: API_TARGET, changeOrigin: true },
  "/openapi.json": { target: API_TARGET, changeOrigin: true },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 8080,
    proxy,
  },
  preview: {
    port: 4173,
    proxy,
  },
  build: {
    // Vendor separado: el chunk base baja de tamaño y el cache del navegador
    // no se invalida en cada cambio de producto.
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          charts: ["recharts"],
          motion: ["motion"],
          markdown: ["marked", "dompurify"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
});
