import { STATUS_COLUMNS } from "../../types/application";
import type { ApplicationTrackerItem } from "../../types/candidate";

// مسیر اصلی خطی ماشین وضعیت، بدون Rejected — Rejected جدا و به‌صورت یک نشان قرمز نمایش داده می‌شود
const MAIN_TRACK = STATUS_COLUMNS.filter((column) => column.value !== "Rejected");

interface ApplicationTrackerCardProps {
  application: ApplicationTrackerItem;
}

export default function ApplicationTrackerCard({ application }: ApplicationTrackerCardProps) {
  const isRejected = application.current_status === "Rejected";
  const currentStepIndex = MAIN_TRACK.findIndex((step) => step.value === application.current_status);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-800">{application.job_title}</h3>
        {isRejected && (
          <span className="shrink-0 rounded-full bg-red-100 px-2.5 py-1 text-xs font-bold text-red-700">
            رد شده
          </span>
        )}
      </div>

      {!isRejected && (
        <div className="flex items-start overflow-x-auto pb-2">
          {MAIN_TRACK.map((step, index) => {
            const isDone = index < currentStepIndex;
            const isCurrent = index === currentStepIndex;
            return (
              <div key={step.value} className="flex shrink-0 items-start">
                <div className="flex flex-col items-center">
                  <div
                    className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
                      isCurrent
                        ? "bg-blue-600 text-white ring-4 ring-blue-100"
                        : isDone
                          ? "bg-emerald-500 text-white"
                          : "bg-slate-200 text-slate-500"
                    }`}
                  >
                    {isDone ? "✓" : index + 1}
                  </div>
                  <span
                    className={`mt-1 w-16 text-center text-[10px] leading-tight ${
                      isCurrent ? "font-bold text-blue-700" : "text-slate-400"
                    }`}
                  >
                    {step.label}
                  </span>
                </div>
                {index < MAIN_TRACK.length - 1 && (
                  <div className={`mt-3.5 h-0.5 w-6 shrink-0 ${isDone ? "bg-emerald-500" : "bg-slate-200"}`} />
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="mt-2 text-xs text-slate-400">
        آخرین به‌روزرسانی: {new Date(application.updated_at).toLocaleDateString("fa-IR")}
      </p>
    </div>
  );
}
