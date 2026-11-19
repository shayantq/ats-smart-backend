import type { ProcessingState } from "../types/processing";

const labels = {
  queued: "در صف تحلیل",
  processing: "در حال پردازش رزومه",
  retrying: "خطای موقت؛ در انتظار تلاش مجدد",
  succeeded: "تحلیل ذخیره شد؛ نتایج همچنان نیازمند بررسی انسانی است",
  failed: "تحلیل ناموفق بود؛ متن استخراج‌شده، در صورت وجود، حفظ شده است",
};
const stages: Record<string, string> = {loading:"خواندن فایل", extraction:"استخراج متن", parsing:"استخراج اطلاعات", inference:"تحلیل مدل", commit:"ذخیرهٔ نتیجه"};
const budgetMessage = "این سند برای ظرفیت فعلی تحلیل بیش از حد طولانی است. متن استخراج‌شده و داده‌های ساختاریافته ذخیره شدند.";

export default function ResumeProcessingStatus({state}: {state?: ProcessingState | null}) {
  if (!state) return null;
  const overBudget = state.status === "failed" && state.error_code === "input_exceeds_model_budget";
  return <p role={state.status === "failed" ? "alert" : "status"} aria-atomic="true" className="my-4 text-caption text-muted">
    {overBudget ? budgetMessage : labels[state.status]}
    {state.status === "processing" && stages[state.stage] && ` — ${stages[state.stage]}`}
    {state.error_code && <> — کد پیگیری: <bdi>{state.error_code}</bdi></>}
  </p>;
}
