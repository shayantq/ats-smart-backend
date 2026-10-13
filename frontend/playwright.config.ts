import { defineConfig, devices } from "@playwright/test";

/**
 * تست‌های E2E (شبیه‌سازی کاربر واقعی در مرورگر) روی کل سیستم در حال اجرا:
 * فرانت‌اند (Nginx) → بک‌اند (FastAPI) → PostgreSQL — همان چیزی که docker compose بالا می‌آورد.
 *
 *   docker compose up -d          (از ریشه‌ی ریپو)
 *   npm run test:e2e              (از همین پوشه)
 *
 * مرورگر: لوکال از Microsoft Edge نصب‌شده روی سیستم استفاده می‌شود (بدون دانلود مرورگر جدا)؛
 * در CI از Chromium خودِ Playwright. با E2E_BROWSER_CHANNEL قابل تغییر است (مثلاً chrome).
 */
const browserChannel = process.env.E2E_BROWSER_CHANNEL ?? (process.env.CI ? undefined : "msedge");
const HR_SESSION_FILE = "e2e/.auth/hr.json";

export default defineConfig({
  testDir: "./e2e",
  // سناریوها روی داده‌ی مشترک یک بورد کار می‌کنند — اجرای پشت‌سرهم و قابل‌پیش‌بینی
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    locale: "fa-IR",
    // صفحه‌ی دسکتاپ معمول کارشناس HR — تا ستون‌های بیشتری از بورد ۹ستونه هم‌زمان دیده شوند
    viewport: { width: 1920, height: 1080 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // ضبط ویدیو به ffmpeg خودِ Playwright نیاز دارد — فقط در CI (لوکال بدون دانلود اضافه)
    video: process.env.CI ? "retain-on-failure" : "off",
  },
  projects: [
    // ۱) ورود واقعی با فرم (خودش یکی از سناریوهای اصلی است) + ذخیره‌ی نشست برای بقیه‌ی تست‌ها
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1920, height: 1080 }, channel: browserChannel },
    },
    // ۲) بقیه‌ی سناریوها با همان نشست HR (بدون ورود مجدد — Rate Limit ورود: ۵ بار در دقیقه)
    {
      name: "e2e",
      testMatch: /.*\.spec\.ts/,
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1920, height: 1080 },
        channel: browserChannel,
        storageState: HR_SESSION_FILE,
      },
    },
  ],
});
