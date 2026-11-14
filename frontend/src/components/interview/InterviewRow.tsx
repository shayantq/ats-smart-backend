import { useState } from "react";
import EvaluationForm from "./EvaluationForm";
import type { Interview } from "../../types/interview";

interface InterviewRowProps {
  interview: Interview;
}

export default function InterviewRow({ interview }: InterviewRowProps) {
  const [isFormOpen, setIsFormOpen] = useState(false);
  const isCompleted = interview.status === "Completed";

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-500 bg-white dark:bg-slate-800 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-bold text-slate-800 dark:text-slate-200">{interview.candidate_name || "بدون نام"}</p>
          <p className="text-xs text-slate-600 dark:text-slate-300">{interview.job_title}</p>
          {interview.scheduled_at && (
            <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
              {new Date(interview.scheduled_at).toLocaleString("fa-IR")}
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {isCompleted ? (
            <span className="rounded-full bg-emerald-100 dark:bg-emerald-950 px-3 py-1 text-xs font-bold text-emerald-700 dark:text-emerald-300">
              تکمیل شده{interview.overall_score !== null ? ` (${interview.overall_score}/۱۰)` : ""}
            </span>
          ) : (
            <button
              onClick={() => setIsFormOpen((open) => !open)}
              className="rounded-md bg-slate-800 dark:bg-slate-700 px-3 py-1.5 text-xs font-semibold text-white dark:text-slate-100 transition-colors hover:bg-slate-950 dark:hover:bg-slate-950"
            >
              {isFormOpen ? "بستن فرم" : "ثبت ارزیابی"}
            </button>
          )}
        </div>
      </div>

      {!isCompleted && isFormOpen && (
        <div className="mt-4">
          <EvaluationForm interview={interview} onSubmitted={() => setIsFormOpen(false)} />
        </div>
      )}

      {isCompleted && interview.feedback_text && (
        <p className="mt-3 rounded-lg bg-slate-50 dark:bg-slate-900 p-3 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
          {interview.feedback_text}
        </p>
      )}
    </div>
  );
}
