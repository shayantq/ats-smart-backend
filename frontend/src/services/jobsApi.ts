import { apiRequest } from "./apiClient";
import type { Job, JobListResponse } from "../types/job";

/** لیست آگهی‌های فعال — مسیر عمومی، نیازی به توکن ندارد */
export async function fetchActiveJobs(): Promise<Job[]> {
  const data = await apiRequest<JobListResponse>("/jobs/?status=Active", { auth: false });
  return data.items;
}
