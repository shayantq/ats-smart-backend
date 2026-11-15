import { memo, useState, type DragEvent, type ButtonHTMLAttributes } from "react";
import CandidateDossier from "./CandidateDossier";
import type { ApplicationListItem } from "../types/application";

interface ApplicationCardProps {
  application: ApplicationListItem;
  isDragging: boolean;
  onDragStart: (event: DragEvent<HTMLDivElement>, application: ApplicationListItem) => void;
  onDragEnd: (event: DragEvent<HTMLDivElement>) => void;
  moveControl?: ButtonHTMLAttributes<HTMLButtonElement>;
  moveLabel?: string;
  canDrag?: boolean;
  onOpenDossier?: () => void;
}

/** رنگ نشان امتیاز هوش مصنوعی بر اساس بازه‌ی امتیاز */
function scoreBadgeStyle(score: number | null): string {
  if (score === null) return "bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300";
  if (score >= 80) return "bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300";
  if (score >= 50) return "bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300";
  return "bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300";
}

function ApplicationCard({
  application,
  isDragging,
  onDragStart,
  onDragEnd,
  moveControl,
  moveLabel,
  canDrag = true,
  onOpenDossier,
}: ApplicationCardProps) {
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  return (
    <>
    <div
      draggable={canDrag}
      data-testid="application-card"
      onDragStart={(event) => onDragStart(event, application)}
      onDragEnd={onDragEnd}
      className={`cursor-grab select-none rounded border border-rule bg-white dark:bg-slate-800 p-4 transition-[opacity,border-color] duration-200 hover:border-slate-400 dark:hover:border-slate-500 active:cursor-grabbing ${
        isDragging ? "opacity-40" : "opacity-100"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <p dir="auto" className="min-w-0 break-words text-sm font-semibold leading-7 text-ink">{application.candidate_name}</p>
        <span
          className={`shrink-0 rounded px-2 py-0.5 text-caption font-medium tabular-nums ${scoreBadgeStyle(
            application.score_ai,
          )}`}
          title="بالاترین امتیاز محاسبه‌شده‌ی هوش مصنوعی"
        >
          {application.score_ai !== null ? `${application.score_ai}%` : "بدون امتیاز"}
        </span>
      </div>
      <p className="mt-3 text-caption text-muted">
        آخرین به‌روزرسانی: {new Date(application.updated_at).toLocaleDateString("fa-IR")}
      </p>
      <button type="button" draggable={false} onClick={() => onOpenDossier ? onOpenDossier() : setIsProfileOpen(true)} aria-label={`مشاهده پرونده ${application.candidate_name}`} className="mt-3 border-t border-rule pt-3 text-caption font-medium text-slate-700 dark:text-slate-200 hover:text-slate-950 dark:hover:text-slate-200">
        مشاهده پرونده <span aria-hidden="true">←</span>
      </button>
      {moveControl && <button type="button" draggable={false} {...moveControl} className="mt-3 block w-full rounded-sm border border-slate-500 px-2 py-2 text-caption text-ink hover:bg-wash aria-disabled:cursor-not-allowed">{moveLabel || "تغییر وضعیت"}</button>}
    </div>
    {isProfileOpen && <CandidateDossier application={application} onClose={() => setIsProfileOpen(false)} />}
    </>
  );
}

export default memo(ApplicationCard);
