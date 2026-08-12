/**
 * تایپ‌ها و ستون‌های بورد کانبان — دقیقاً منطبق بر ماشین وضعیت بک‌اند
 * (app/core/state_machine.py).
 */

export type ApplicationStatus =
  | "Draft"
  | "Applied"
  | "Screening"
  | "Technical Interview"
  | "HR Interview"
  | "Offer"
  | "Accepted"
  | "Hired"
  | "Rejected";

/** ترتیب و برچسب فارسی ستون‌های بورد — همان ترتیب مسیر خطی ماشین وضعیت بک‌اند */
export const STATUS_COLUMNS: { value: ApplicationStatus; label: string }[] = [
  { value: "Draft", label: "پیش‌نویس" },
  { value: "Applied", label: "ثبت اولیه" },
  { value: "Screening", label: "غربالگری" },
  { value: "Technical Interview", label: "مصاحبه فنی" },
  { value: "HR Interview", label: "مصاحبه HR" },
  { value: "Offer", label: "پیشنهاد شغلی" },
  { value: "Accepted", label: "پذیرفته‌شده" },
  { value: "Hired", label: "استخدام نهایی" },
  { value: "Rejected", label: "رد شده" },
];

/** ساختار هر کارت روی بورد کانبان — خروجی GET /api/v1/applications/ */
export interface ApplicationListItem {
  application_id: string;
  candidate_id: string;
  candidate_name: string;
  current_status: ApplicationStatus;
  score_ai: number | null;
  updated_at: string;
}

export interface ApplicationListResponse {
  total: number;
  items: ApplicationListItem[];
}

/** خروجی موفق PUT /api/v1/applications/{id}/status */
export interface ApplicationStatusUpdateResult {
  application_id: string;
  previous_status: ApplicationStatus;
  new_status: ApplicationStatus;
  updated_at: string;
}
