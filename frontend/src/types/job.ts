/** ساختار یک آگهی شغلی — خروجی GET /api/v1/jobs/ */
export interface Job {
  job_id: string;
  title: string;
  department: string | null;
  description: string | null;
  skills_required: string[];
  salary_range: string | null;
  status: string;
  created_by: string;
  created_at: string | null;
}

/** خروجی GET /api/v1/jobs/ — صفحه‌بندی مبتنی بر نشانگر (Cursor Pagination) */
export interface JobListResponse {
  items: Job[];
  next_cursor: string | null;
  previous_cursor: string | null;
  has_next: boolean;
  has_previous: boolean;
}
