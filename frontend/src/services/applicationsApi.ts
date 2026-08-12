/**
 * فراخوانی اندپوینت‌های بک‌اند مربوط به بورد کانبان:
 * - GET  /api/v1/applications/?job_id=...   لیست کارت‌های یک آگهی خاص
 * - PUT  /api/v1/applications/{id}/status   جابه‌جایی وضعیت یک کارت
 */

import { apiRequest } from "./apiClient";
import type {
  ApplicationListItem,
  ApplicationListResponse,
  ApplicationStatus,
  ApplicationStatusUpdateResult,
} from "../types/application";

export async function fetchApplicationsForJob(jobId: string): Promise<ApplicationListItem[]> {
  const data = await apiRequest<ApplicationListResponse>(
    `/applications/?job_id=${encodeURIComponent(jobId)}`,
  );
  return data.items;
}

export interface UpdateApplicationStatusPayload {
  applicationId: string;
  currentStatus: ApplicationStatus;
  newStatus: ApplicationStatus;
}

export async function updateApplicationStatus({
  applicationId,
  currentStatus,
  newStatus,
}: UpdateApplicationStatusPayload): Promise<ApplicationStatusUpdateResult> {
  return apiRequest<ApplicationStatusUpdateResult>(`/applications/${applicationId}/status`, {
    method: "PUT",
    body: JSON.stringify({ current_status: currentStatus, new_status: newStatus }),
  });
}
