import { e2eData, expect, test } from "./fixtures";

/**
 * سناریوی اصلی ورود: ربات مرورگر را باز می‌کند، ایمیل و رمز را در فرم می‌نویسد، دکمه‌ی
 * «ورود» را می‌زند و بررسی می‌کند که داشبورد HR و بورد کانبان لود شده است.
 * نشست ساخته‌شده برای بقیه‌ی سناریوها ذخیره می‌شود (playwright.config.ts → storageState).
 */
test("کارشناس HR از طریق فرم ورود وارد می‌شود و بورد کانبان لود می‌شود", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "ورود به ATS Smart" })).toBeVisible();
  await page.getByLabel("ایمیل").fill(e2eData.hrEmail);
  await page.getByLabel("رمز عبور").fill(e2eData.password);
  await page.getByRole("button", { name: "ورود" }).click();

  await expect(page.getByRole("heading", { name: "داشبورد کارشناس منابع انسانی" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "بورد کانبان" })).toHaveAttribute("aria-selected", "true");
  await page.getByLabel("آگهی شغلی").selectOption({ label: e2eData.jobTitle });
  await expect(page.getByTestId("kanban-board")).toBeVisible();

  await page.context().storageState({ path: "e2e/.auth/hr.json" });
});
