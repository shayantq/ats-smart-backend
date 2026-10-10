import { STATUS_COLUMNS } from "../src/types/application";
import { cardInColumn, e2eData, expect, openSeededBoard, test } from "./fixtures";

// برچسب ستون‌ها مستقیم از همان منبعی که UI با آن رندر می‌شود (نه کپی دستی)
const COLUMN_LABELS = STATUS_COLUMNS.map((column) => column.label);

test("بورد کانبان: همه‌ی ستون‌ها به ترتیب و هر کارت در ستون درست خودش", async ({ page }) => {
  await openSeededBoard(page);

  const columns = page.getByTestId("kanban-board").getByRole("region");
  await expect(columns).toHaveCount(COLUMN_LABELS.length);
  for (const [index, label] of COLUMN_LABELS.entries()) {
    await expect(columns.nth(index)).toHaveAttribute("aria-label", label);
  }

  await expect(cardInColumn(page, "Draft", "Sara E2E")).toBeVisible();
  await expect(cardInColumn(page, "Screening", "Reza E2E")).toBeVisible();
  await expect(cardInColumn(page, "Offer", "Nima E2E")).toBeVisible();
  await expect(cardInColumn(page, "Offer", "Nima E2E")).toContainText("64%");

  // سربرگ: کاربر لاگین‌شده و دکمه‌ی خروج سر جایشان
  await expect(page.getByRole("banner")).toContainText(e2eData.hrEmail);
  await expect(page.getByRole("button", { name: "خروج" })).toBeVisible();
});

test("درگ و دراپ مجاز: کارت به مرحله‌ی بعد می‌رود و پس از رفرش هم همان‌جا می‌ماند", async ({ page }) => {
  await openSeededBoard(page);
  const draftCard = cardInColumn(page, "Draft", "Sara E2E");
  await expect(draftCard).toBeVisible();

  await draftCard.dragTo(page.getByTestId("kanban-column-Applied"));

  await expect(page.getByRole("alert").filter({ hasText: "وضعیت کارجو با موفقیت به‌روزرسانی شد." })).toBeVisible();
  await expect(cardInColumn(page, "Applied", "Sara E2E")).toBeVisible();
  await expect(cardInColumn(page, "Draft", "Sara E2E")).toHaveCount(0);

  // ماندگاری: تغییر واقعاً در دیتابیس ثبت شده، نه فقط روی صفحه
  await page.reload();
  await page.getByLabel("آگهی شغلی").selectOption({ label: e2eData.jobTitle });
  await expect(cardInColumn(page, "Applied", "Sara E2E")).toBeVisible();
});

test("درگ و دراپ غیرمجاز: پرش از غربالگری به مصاحبه HR (بدون مصاحبه فنی) رد می‌شود و کارت سر جایش برمی‌گردد", async ({
  page,
}) => {
  await openSeededBoard(page);
  const screeningCard = cardInColumn(page, "Screening", "Reza E2E");
  await expect(screeningCard).toBeVisible();

  await screeningCard.dragTo(page.getByTestId("kanban-column-HR Interview"));

  await expect(page.getByRole("alert").filter({ hasText: "این جابه‌جایی طبق قوانین ماشین وضعیت مجاز نیست." })).toBeVisible();
  await expect(cardInColumn(page, "Screening", "Reza E2E")).toBeVisible();
  await expect(cardInColumn(page, "HR Interview", "Reza E2E")).toHaveCount(0);

  // پس از رفرش هم کارت همچنان در غربالگری است — دیتابیس تغییری نکرده
  await page.reload();
  await page.getByLabel("آگهی شغلی").selectOption({ label: e2eData.jobTitle });
  await expect(cardInColumn(page, "Screening", "Reza E2E")).toBeVisible();
});

test("خروج: کاربر به صفحه‌ی ورود برمی‌گردد", async ({ page }) => {
  await openSeededBoard(page);

  await page.getByRole("button", { name: "خروج" }).click();

  await expect(page.getByRole("button", { name: "ورود" })).toBeVisible();
});
