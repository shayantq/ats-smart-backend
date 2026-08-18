/**
 * فراخوانی اندپوینت‌های بک‌اند مربوط به پورتال کارجو:
 * - GET/PUT /api/v1/candidates/me                          پروفایل شخصی
 * - GET     /api/v1/candidates/me/applications                رهگیر وضعیت
 * - GET     /api/v1/candidates/me/offers                       صندوق ورودی پیشنهادها
 * - PUT     /api/v1/candidates/me/applications/{id}/respond     پاسخ به یک پیشنهاد
 * - POST    /api/v1/resumes/upload                                آپلود رزومه
 */

import { apiRequest, apiUploadFile } from "./apiClient";
import type {
  ApplicationTrackerItem,
  CandidateProfile,
  CandidateProfileUpdatePayload,
  OfferDecision,
  OfferInboxItem,
  OfferResponseResult,
  ResumeUploadResult,
} from "../types/candidate";

export async function fetchMyProfile(): Promise<CandidateProfile> {
  return apiRequest<CandidateProfile>("/candidates/me");
}

export async function updateMyProfile(payload: CandidateProfileUpdatePayload): Promise<CandidateProfile> {
  return apiRequest<CandidateProfile>("/candidates/me", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function fetchMyApplications(): Promise<ApplicationTrackerItem[]> {
  const data = await apiRequest<{ total: number; items: ApplicationTrackerItem[] }>(
    "/candidates/me/applications",
  );
  return data.items;
}

export async function fetchMyOffers(): Promise<OfferInboxItem[]> {
  const data = await apiRequest<{ total: number; items: OfferInboxItem[] }>("/candidates/me/offers");
  return data.items;
}

export async function respondToOffer(
  applicationId: string,
  decision: OfferDecision,
): Promise<OfferResponseResult> {
  return apiRequest<OfferResponseResult>(`/candidates/me/applications/${applicationId}/respond`, {
    method: "PUT",
    body: JSON.stringify({ decision }),
  });
}

export interface UploadResumePayload {
  jobId: string;
  file: File;
}

export async function uploadResume({ jobId, file }: UploadResumePayload): Promise<ResumeUploadResult> {
  const formData = new FormData();
  formData.append("job_id", jobId);
  formData.append("file", file);
  return apiUploadFile<ResumeUploadResult>("/resumes/upload", formData);
}
