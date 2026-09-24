import { apiRequest } from "./apiClient";
import type { ApplicationsTrendResponse, RecruitmentFunnelResponse } from "../types/analytics";

/** GET /api/v1/analytics/funnel — فقط Admin/HR_Manager (۴۰۳ برای بقیه‌ی نقش‌ها) */
export async function fetchRecruitmentFunnel(params: { jobId?: string } = {}): Promise<RecruitmentFunnelResponse> {
  const searchParams = new URLSearchParams();
  if (params.jobId) {
    searchParams.set("job_id", params.jobId);
  }
  const query = searchParams.toString();
  return apiRequest<RecruitmentFunnelResponse>(`/analytics/funnel${query ? `?${query}` : ""}`);
}

/** GET /api/v1/analytics/applications-trend — فقط Admin/HR_Manager (۴۰۳ برای بقیه‌ی نقش‌ها) */
export async function fetchApplicationsTrend(
  params: { days?: number; jobId?: string } = {},
): Promise<ApplicationsTrendResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set("days", String(params.days ?? 30));
  if (params.jobId) {
    searchParams.set("job_id", params.jobId);
  }
  return apiRequest<ApplicationsTrendResponse>(`/analytics/applications-trend?${searchParams.toString()}`);
}
