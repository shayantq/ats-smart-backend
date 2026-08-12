import type { DragEvent } from "react";
import type { ApplicationListItem } from "../types/application";

interface ApplicationCardProps {
  application: ApplicationListItem;
  isDragging: boolean;
  onDragStart: (event: DragEvent<HTMLDivElement>, application: ApplicationListItem) => void;
  onDragEnd: (event: DragEvent<HTMLDivElement>) => void;
}

/** رنگ نشان امتیاز هوش مصنوعی بر اساس بازه‌ی امتیاز */
function scoreBadgeStyle(score: number | null): string {
  if (score === null) return "bg-slate-200 text-slate-500";
  if (score >= 80) return "bg-emerald-100 text-emerald-700";
  if (score >= 50) return "bg-amber-100 text-amber-700";
  return "bg-red-100 text-red-700";
}

export default function ApplicationCard({
  application,
  isDragging,
  onDragStart,
  onDragEnd,
}: ApplicationCardProps) {
  return (
    <div
      draggable
      onDragStart={(event) => onDragStart(event, application)}
      onDragEnd={onDragEnd}
      className={`cursor-grab select-none rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition-opacity active:cursor-grabbing ${
        isDragging ? "opacity-40" : "opacity-100"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-semibold text-slate-800">{application.candidate_name}</p>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold ${scoreBadgeStyle(
            application.score_ai,
          )}`}
          title="بالاترین امتیاز محاسبه‌شده‌ی هوش مصنوعی"
        >
          {application.score_ai !== null ? `${application.score_ai}%` : "بدون امتیاز"}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-400">
        آخرین به‌روزرسانی: {new Date(application.updated_at).toLocaleDateString("fa-IR")}
      </p>
    </div>
  );
}
