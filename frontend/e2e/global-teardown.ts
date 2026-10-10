import { runBackendSeed } from "./backend-seed";

/** پس از کل تست‌ها: حذف دقیق همان داده‌های آزمایشی این اجرا (و فقط همان‌ها) از دیتابیس. */
export default async function globalTeardown() {
  const runId = process.env.E2E_RUN_ID;
  if (!runId) return;
  const result = runBackendSeed<{ deletedUsers: number; deletedApplications: number }>("cleanup", runId);
  console.log(`[e2e] داده‌ی آزمایشی پاک شد (run_id=${runId}, کاربر: ${result.deletedUsers}, درخواست: ${result.deletedApplications})`);
}
