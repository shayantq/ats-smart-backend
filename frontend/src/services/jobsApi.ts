import { fetchAllCursorPages } from "./apiClient";
import type { Job } from "../types/job";

/** لیست آگهی‌های فعال — مسیر عمومی، نیازی به توکن ندارد */
export async function fetchActiveJobs(): Promise<Job[]> {
  return fetchAllCursorPages<Job>("/jobs/", { params: { status: "Active" }, auth: false });
}
