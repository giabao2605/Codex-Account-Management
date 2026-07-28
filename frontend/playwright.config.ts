import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:8878",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chrome",
      use: {
        ...devices["Desktop Chrome"],
        channel: "chrome",
      },
    },
  ],
  webServer: {
    command: (
      "python -m uvicorn tests.production_frontend_server:app " +
      "--host 127.0.0.1 --port 8878"
    ),
    cwd: "..",
    url: "http://127.0.0.1:8878/api/health",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
