import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchInterviews } from "../../services/interviewsApi";
import InterviewRow from "./InterviewRow";

function getTodayDateString(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function TodayInterviewsPanel() {
  const [showAllPending, setShowAllPending] = useState(false);
  const todayDate = getTodayDateString();

  // بدون رفرش صفحه: React Query لیست را واکشی و کش می‌کند؛ بعد از ثبت هر
  // ارزیابی (در EvaluationForm)، همین کوئری invalidate می‌شود و خودکار رفرش می‌شود.
  const {
    data: interviews = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["interviews", showAllPending ? "all-pending" : todayDate],
    queryFn: () => fetchInterviews(showAllPending ? { status: "Pending" } : { date: todayDate }),
  });

  return (
    <div>
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-sm font-bold text-slate-700">
          {showAllPending ? "همه‌ی فرم‌های ارزیابی معوقه" : "مصاحبه‌های امروز"}
        </h2>
        <button
          onClick={() => setShowAllPending((value) => !value)}
          className="self-start text-xs font-semibold text-blue-600 hover:underline sm:self-auto"
        >
          {showAllPending ? "فقط امروز" : "نمایش همه‌ی معوقه‌ها"}
        </button>
      </div>

      {isLoading && <p className="p-4 text-sm text-slate-500">در حال بارگذاری...</p>}

      {isError && (
        <p className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-600">
          خطا در دریافت لیست مصاحبه‌ها. توکن دسترسی را بررسی کن.
        </p>
      )}

      {!isLoading && !isError && interviews.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
          {showAllPending ? "هیچ فرم ارزیابی معوقه‌ای نیست." : "امروز مصاحبه‌ای زمان‌بندی نشده."}
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {interviews.map((interview) => (
          <InterviewRow key={interview.interview_id} interview={interview} />
        ))}
      </div>
    </div>
  );
}
