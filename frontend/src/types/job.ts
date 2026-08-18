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

export interface JobListResponse {
  total: number;
  items: Job[];
}
