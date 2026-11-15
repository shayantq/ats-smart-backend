/**
 * فراخوانی اندپوینت‌های بک‌اند مربوط به بورد کانبان:
 * - GET  /api/v1/applications/?job_id=...   لیست کارت‌های یک آگهی خاص
 * - PUT  /api/v1/applications/{id}/status   جابه‌جایی وضعیت یک کارت
 */

import { apiRequest, fetchAllCursorPages } from "./apiClient";

export interface ApplicationDossier {
  application_id: string;
  resume_id: string | null;
  raw_text: string | null;
  parsed_data: Record<string, unknown> | null;
  skill_analysis: Record<string, unknown> | null;
  agent_analysis: Record<string, unknown> | null;
}

export function fetchApplicationDossier(applicationId: string): Promise<ApplicationDossier> {
  return apiRequest<ApplicationDossier>(`/applications/${applicationId}/dossier`);
}
import type {
  ApplicationListItem,
  ApplicationStatus,
  ApplicationStatusUpdateResult,
  ApplicationListResponse,
} from "../types/application";

export function fetchApplicationPage(jobId: string, status: ApplicationStatus, cursor: string | null, signal?: AbortSignal): Promise<ApplicationListResponse> {
  const params = new URLSearchParams({job_id:jobId,current_status:status,limit:"50"});
  if(cursor) params.set("cursor",cursor);
  return apiRequest(`/applications/?${params}`,{signal});
}

export async function fetchApplicationsForJob(jobId: string): Promise<ApplicationListItem[]> {
  return fetchAllCursorPages<ApplicationListItem>("/applications/", { params: { job_id: jobId } });
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
