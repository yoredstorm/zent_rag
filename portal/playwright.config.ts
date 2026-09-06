import { defineConfig, devices } from "@playwright/test";

const E2E_PORT = Number(process.env.E2E_PORT || 8090);
const BASE_URL = process.env.E2E_BASE_URL || `http://127.0.0.1:${E2E_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    locale: "es-PE",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer:
    process.env.E2E_EXTERNAL === "1"
      ? undefined
      : {
          command: `npm run dev -- --port ${E2E_PORT} --strictPort --host 127.0.0.1`,
          url: BASE_URL,
          reuseExistingServer: true,
          timeout: 120_000,
        },
});