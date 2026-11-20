import type { ProcessingState } from "../types/processing";

const labels = {
  queued: "در صف تحلیل",
  processing: "در حال پردازش رزومه",
  retrying: "خطای موقت؛ در انتظار تلاش مجدد",
  succeeded: "تحلیل ذخیره شد؛ نتایج همچنان نیازمند بررسی انسانی است",
  failed: "تحلیل ناموفق بود؛ متن استخراج‌شده، در صورت وجود، حفظ شده است",
};
const stages: Record<string, string> = {loading:"خواندن فایل", extraction:"استخراج متن", parsing:"استخراج اطلاعات", inference:"تحلیل مدل", commit:"ذخیرهٔ نتیجه"};
const failureMessages = new Map([
  ["input_exceeds_model_budget", "این سند برای ظرفیت فعلی تحلیل بیش از حد طولانی است. متن استخراج‌شده و داده‌های ساختاریافته ذخیره شدند."],
  ["incomplete_generation", "پاسخ مدل کامل نشد. متن استخراج‌شدهٔ رزومه ذخیره شد."],
  ["context_limit_exceeded", "این سند از ظرفیت فعلی مدل طولانی‌تر است. متن استخراج‌شدهٔ رزومه ذخیره شد."],
  ["engine_deadline_exceeded", "پردازش مدل بیش از حد طول کشید و متوقف شد. متن استخراج‌شدهٔ رزومه ذخیره شد."],
]);
const reviewMessages = {
  incomplete_input: "اطلاعات مستند ذخیره شد. شواهد ورودی مدل ناقص بود و پرونده نیازمند بازبینی است",
  matching_conflict: "اطلاعات مستند ذخیره شد. نتیجهٔ مدل با شواهد شروط آگهی همخوانی ندارد و نیازمند بازبینی است",
};

export default function ResumeProcessingStatus({state, reviewReason}: {state?: ProcessingState | null; reviewReason?: keyof typeof reviewMessages}) {
  if (!state) return null;
  const failure = state.status === "failed" && state.error_code && failureMessages.get(state.error_code);
  const review = state.status === "succeeded" && reviewReason && reviewMessages[reviewReason];
  return <p role={state.status === "failed" ? "alert" : "status"} aria-atomic="true" className="my-4 text-caption text-muted">
    {failure || review || labels[state.status]}
    {state.status === "processing" && stages[state.stage] && ` — ${stages[state.stage]}`}
    {state.error_code && <> — کد پیگیری: <bdi>{state.error_code}</bdi></>}
  </p>;
}
