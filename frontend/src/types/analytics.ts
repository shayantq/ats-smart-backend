/**
 * تایپ‌ها — دقیقاً منطبق بر خروجی بک‌اند (app/schemas/analytics.py):
 * GET /api/v1/analytics/funnel
 * GET /api/v1/analytics/applications-trend
 */

export interface FunnelStageCount {
  stage: string;
  count: number;
}

export interface RecruitmentFunnelResponse {
  job_id: string | null;
  stages: FunnelStageCount[];
}

export interface DailyApplicationCount {
  /** تاریخ به فرمت ISO (YYYY-MM-DD) */
  date: string;
  count: number;
}

export interface ApplicationsTrendResponse {
  days: number;
  job_id: string | null;
  series: DailyApplicationCount[];
}
