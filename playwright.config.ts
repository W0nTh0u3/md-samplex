import { defineConfig } from "@playwright/test";
const port = Number(process.env.PLE_TEST_PORT ?? 3100);
if (!Number.isInteger(port) || port < 1024 || port > 65535)
  throw new Error("PLE_TEST_PORT must be an integer from 1024 to 65535.");
const origin = `http://localhost:${port}`;
export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  expect: { timeout: 15000 },
  use: {
    baseURL: origin,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command:
      process.env.PLE_TEST_PRODUCTION === "true"
        ? `npm start -- --port ${port}`
        : `npm run dev -- --port ${port}`,
    url: origin,
    reuseExistingServer: false,
    timeout: 120000,
    env: {
      PLE_DEMO_MODE: "true",
      APP_ORIGIN: origin,
      // Keep automated preview tests isolated from configured cloud accounts.
      SUPABASE_SECRET_KEY: "",
    },
  },
});
