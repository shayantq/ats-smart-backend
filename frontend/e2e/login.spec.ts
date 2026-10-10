import { e2eData, expect, test } from "./fixtures";

test.describe("فرم ورود", () => {
  // این گروه بدون نشست ذخیره‌شده اجرا می‌شود (کاربر هنوز وارد نشده)
  test.use({ storageState: { cookies: [], origins: [] } });

  test("رمز اشتباه: پیام خطا نمایش داده می‌شود و کاربر روی صفحه‌ی ورود می‌ماند", async ({ page }) => {
    await page.goto("/");

    await page.getByLabel("ایمیل").fill(e2eData.hrEmail);
    await page.getByLabel("رمز عبور").fill("definitely-wrong-password");
    await page.getByRole("button", { name: "ورود" }).click();

    await expect(page.getByRole("alert")).toHaveText("ایمیل یا رمز عبور نادرست است.");
    await expect(page.getByRole("button", { name: "ورود" })).toBeEnabled();
    await expect(page.getByRole("heading", { name: "داشبورد کارشناس منابع انسانی" })).toHaveCount(0);
  });

  test("فیلدهای خالی: مرورگر پیش از ارسال جلوی فرم را می‌گیرد", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("button", { name: "ورود" }).click();

    const emailIsMissing = await page.getByLabel("ایمیل").evaluate((input: HTMLInputElement) => input.validity.valueMissing);
    expect(emailIsMissing).toBe(true);
    await expect(page.getByRole("heading", { name: "ورود به ATS Smart" })).toBeVisible();
  });
});
