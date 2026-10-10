import { test as base, expect, type Page } from "@playwright/test";

/**
 * نسخه‌ی گسترش‌یافته‌ی test که «کرش کلاینت» را تشخیص می‌دهد: هر خطای جاوااسکریپت
 * مدیریت‌نشده در صفحه (pageerror) یا console.error برنامه، تست را Fail می‌کند.
 * خطاهای شبکه‌ای عمدی (مثلاً 401 ورود اشتباه یا 400 جابه‌جایی غیرمجاز) خطای کلاینت نیستند
 * و نادیده گرفته می‌شوند — آن‌ها رفتار درست برنامه‌اند که خودِ تست‌ها بررسی می‌کنند.
 */
export const test = base.extend<{ clientErrors: string[] }>({
  clientErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
      page.on("console", (message) => {
        if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
          errors.push(`console.error: ${message.text()}`);
        }
      });
      await use(errors);
      expect(errors, "مرورگر نباید هیچ خطای جاوااسکریپت/کرش داشته باشد").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export const e2eData = {
  get hrEmail() {
    return process.env.E2E_HR_EMAIL ?? "";
  },
  get password() {
    return process.env.E2E_PASSWORD ?? "";
  },
  get jobTitle() {
    return process.env.E2E_JOB_TITLE ?? "";
  },
};

/** باز کردن داشبورد HR و انتخاب آگهی داده‌ی آزمایشی همین اجرا */
export async function openSeededBoard(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "داشبورد کارشناس منابع انسانی" })).toBeVisible();
  await page.getByLabel("آگهی شغلی").selectOption({ label: e2eData.jobTitle });
  await expect(page.getByTestId("kanban-board")).toBeVisible();
}

/** کارت یک کارجو داخل ستون یک وضعیت مشخص */
export function cardInColumn(page: Page, status: string, candidateName: string) {
  return page.getByTestId(`kanban-column-${status}`).getByTestId("application-card").filter({ hasText: candidateName });
}
