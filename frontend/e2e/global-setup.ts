import { randomBytes } from "node:crypto";
import { runBackendSeed } from "./backend-seed";

interface SeedResult {
  hrEmail: string;
  password: string;
  jobTitle: string;
  jobId: string;
}

/**
 * پیش از کل تست‌ها: ساخت داده‌ی آزمایشی (HR + آگهی + ۳ کارجو روی بورد) با یک شناسه‌ی اجرای
 * یکتا. مقادیر از طریق متغیرهای محیطی به تست‌ها می‌رسند.
 */
export default async function globalSetup() {
  const runId = randomBytes(4).toString("hex");
  const seed = runBackendSeed<SeedResult>("seed", runId);

  process.env.E2E_RUN_ID = runId;
  process.env.E2E_HR_EMAIL = seed.hrEmail;
  process.env.E2E_PASSWORD = seed.password;
  process.env.E2E_JOB_TITLE = seed.jobTitle;
  console.log(`[e2e] داده‌ی آزمایشی ساخته شد (run_id=${runId}, آگهی: ${seed.jobTitle})`);
}
