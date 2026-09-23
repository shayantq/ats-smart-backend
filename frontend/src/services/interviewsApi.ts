/**
 * فراخوانی اندپوینت‌های بک‌اند مربوط به سرویس مصاحبه‌ها:
 * - GET /api/v1/interviews/?date=&status=&application_id=   لیست مصاحبه‌ها (فیلترپذیر)
 * - PUT /api/v1/interviews/{id}/evaluation                    ثبت ارزیابی و نمرات
 */

import { apiRequest, fetchAllCursorPages } from "./apiClient";
import type { Interview, InterviewEvaluationPayload, InterviewStatus } from "../types/interview";

export interface FetchInterviewsParams {
  date?: string; // فرمت YYYY-MM-DD
  status?: InterviewStatus;
  applicationId?: string;
}

export async function fetchInterviews(params: FetchInterviewsParams = {}): Promise<Interview[]> {
  const queryParams: Record<string, string> = {};
  if (params.date) queryParams.date = params.date;
  if (params.status) queryParams.status = params.status;
  if (params.applicationId) queryParams.application_id = params.applicationId;

  return fetchAllCursorPages<Interview>("/interviews/", { params: queryParams });
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
