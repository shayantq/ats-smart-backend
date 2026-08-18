import type { ApplicationStatus } from "./application";

/** پروفایل کامل کارجوی لاگین‌شده */
export interface CandidateProfile {
  candidate_id: string;
  email: string;
  first_name: string;
  last_name: string;
  phone: string | null;
  skills: string[];
}

/** بدنه‌ی ویرایش پروفایل — هر فیلد اختیاری است (Partial Update) */
export interface CandidateProfileUpdatePayload {
  first_name?: string;
  last_name?: string;
  phone?: string;
  skills?: string[];
}

/** یک ردیف از سیستم رهگیر وضعیت */
export interface ApplicationTrackerItem {
  application_id: string;
  job_id: string;
  job_title: string;
  current_status: ApplicationStatus;
  updated_at: string;
}

/** یک پیشنهاد شغلی فعال در صندوق ورودی */
export interface OfferInboxItem {
  application_id: string;
  job_id: string;
  job_title: string;
  company_name: string | null;
  updated_at: string;
}

export type OfferDecision = "accept" | "reject";

export interface OfferResponseResult {
  application_id: string;
  new_status: ApplicationStatus;
  message: string;
}

export interface ResumeUploadResult {
  application_id: string;
  status: ApplicationStatus;
  message: string;
}
