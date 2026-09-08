/**
 * فراخوانی اندپوینت‌های بک‌اند مربوط به سرویس مصاحبه‌ها:
 * - GET /api/v1/interviews/?date=&status=&application_id=   لیست مصاحبه‌ها (فیلترپذیر)
 * - PUT /api/v1/interviews/{id}/evaluation                    ثبت ارزیابی و نمرات
 */

import { apiRequest } from "./apiClient";
import type { Interview, InterviewEvaluationPayload, InterviewListResponse, InterviewStatus } from "../types/interview";

export interface FetchInterviewsParams {
  date?: string; // فرمت YYYY-MM-DD
  status?: InterviewStatus;
  applicationId?: string;
}

export async function fetchInterviews(params: FetchInterviewsParams = {}): Promise<Interview[]> {
  const searchParams = new URLSearchParams();
  if (params.date) searchParams.set("date", params.date);
  if (params.status) searchParams.set("status", params.status);
  if (params.applicationId) searchParams.set("application_id", params.applicationId);

  const query = searchParams.toString();
  const path = query ? `/interviews/?${query}` : "/interviews/";

  const data = await apiRequest<InterviewListResponse>(path);
  return data.items;
}

export async function submitInterviewEvaluation(
  interviewId: string,
  payload: InterviewEvaluationPayload,
): Promise<Interview> {
  return apiRequest<Interview>(`/interviews/${interviewId}/evaluation`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
