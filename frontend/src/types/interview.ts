/** ستون‌های وضعیت فرم ارزیابی — دقیقاً منطبق بر بک‌اند (app/models/process.py) */
export type InterviewStatus = "Pending" | "Completed";

/**
 * معیارهای مجاز نمره‌دهی — دقیقاً همان مجموعه‌ی ثابتی که بک‌اند می‌پذیرد
 * (app/schemas/interviews.py: ALLOWED_EVALUATION_CRITERIA)
 */
export const EVALUATION_CRITERIA: { key: string; label: string }[] = [
  { key: "technical_skill", label: "مهارت فنی" },
  { key: "problem_solving", label: "حل مسئله" },
  { key: "communication", label: "مهارت ارتباطی" },
  { key: "culture_fit", label: "تناسب فرهنگی" },
];

/** ساختار یک مصاحبه — خروجی GET/POST/PUT مسیرهای /api/v1/interviews */
export interface Interview {
  interview_id: string;
  application_id: string;
  interviewer_id: string;
  interviewer_name: string;
  candidate_name: string;
  job_title: string;
  scheduled_at: string | null;
  meeting_link: string | null;
  status: InterviewStatus;
  evaluation_scores: Record<string, number> | null;
  overall_score: number | null;
  feedback_text: string | null;
  evaluated_at: string | null;
}

export interface InterviewListResponse {
  total: number;
  items: Interview[];
}

/** بدنه‌ی درخواست PUT /interviews/{id}/evaluation */
export interface InterviewEvaluationPayload {
  evaluation_scores: Record<string, number>;
  feedback_text: string;
}
