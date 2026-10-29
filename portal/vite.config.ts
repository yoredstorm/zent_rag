/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const API_TARGET = process.env.VITE_API_PROXY || "http://127.0.0.1:8000";

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
    // React resuelve su build de producción si NODE_ENV no es development/test
    // y ahí `react.act` no existe: @testing-library/react falla al renderizar.
    env: { NODE_ENV: "development" },
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    // La suite incluye pantallas grandes (Agent Studio, Evaluación). En CI y
    // en máquinas de 2-4 núcleos, correr 130 archivos jsdom a la vez ahoga los
    // workers y produce timeouts falsos. El límite y los tiempos son de test,
    // no del producto.
    maxWorkers: 4,
    testTimeout: 60_000,
    hookTimeout: 30_000,
  },
});
