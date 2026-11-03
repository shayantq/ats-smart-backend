import { apiRequest, fetchAllCursorPages } from "./apiClient";
import type { Job, JobCreatePayload } from "../types/job";

/** ساخت و انتشار آگهی تازه برای سازمان کاربر لاگین‌شده (Admin/HR_Manager) */
export async function createJob(payload: JobCreatePayload): Promise<Job> {
  return apiRequest<Job>("/jobs/", { method: "POST", body: JSON.stringify(payload) });
}

/** لیست آگهی‌های فعال — مسیر عمومی، نیازی به توکن ندارد */
export async function fetchActiveJobs(): Promise<Job[]> {
  return fetchAllCursorPages<Job>("/jobs/", { params: { status: "Active" }, auth: false });
}
