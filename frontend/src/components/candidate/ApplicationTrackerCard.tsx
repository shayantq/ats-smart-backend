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
    <div className="editorial-panel">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 text-heading text-ink [overflow-wrap:anywhere]">{application.job_title}</h3>
        {isRejected && (
          <span className="shrink-0 rounded-full bg-red-100 px-2.5 py-1 text-xs font-bold text-red-700">
            رد شده
          </span>
        )}
      </div>

      {!isRejected && (
        <ol aria-label="مراحل درخواست" className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4">
          {MAIN_TRACK.map((step, index) => {
            const isDone = index < currentStepIndex;
            const isCurrent = index === currentStepIndex;
            return (
              <li key={step.value} aria-current={isCurrent ? "step" : undefined} className="flex min-w-0 items-start gap-2">
                  <div
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-sm border text-xs font-medium ${
                      isCurrent
                        ? "border-ink bg-ink text-white"
                        : isDone
                          ? "border-slate-400 bg-wash text-ink"
                          : "border-rule text-muted"
                    }`}
                  >
                    {isDone ? "✓" : index + 1}
                  </div>
                  <span
                    className={`text-caption ${
                      isCurrent ? "font-semibold text-ink" : "text-muted"
                    }`}
                  >
                    {step.label}
                  </span>
              </li>
            );
          })}
        </ol>
      )}

      <p className="mt-2 text-caption text-muted">
        آخرین به‌روزرسانی: {new Date(application.updated_at).toLocaleDateString("fa-IR")}
      </p>
    </div>
  );
}
