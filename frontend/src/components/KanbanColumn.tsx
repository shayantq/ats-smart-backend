import { useState, type DragEvent } from "react";
import ApplicationCard from "./ApplicationCard";
import type { ApplicationListItem, ApplicationStatus } from "../types/application";

interface KanbanColumnProps {
  status: ApplicationStatus;
  label: string;
  applications: ApplicationListItem[];
  draggedApplicationId: string | null;
  onDragStart: (event: DragEvent<HTMLDivElement>, application: ApplicationListItem) => void;
  onDragEnd: (event: DragEvent<HTMLDivElement>) => void;
  onDropOnColumn: (status: ApplicationStatus) => void;
}

export default function KanbanColumn({
  status,
  label,
  applications,
  draggedApplicationId,
  onDragStart,
  onDragEnd,
  onDropOnColumn,
}: KanbanColumnProps) {
  const [isOver, setIsOver] = useState(false);

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setIsOver(true);
      }}
      onDragLeave={() => setIsOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsOver(false);
        onDropOnColumn(status);
      }}
      className={`flex w-72 shrink-0 flex-col rounded-xl border p-3 transition-colors sm:w-80 ${
        isOver ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-slate-50"
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-bold text-slate-700">{label}</h3>
        <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-semibold text-slate-600">
          {applications.length}
        </span>
      </div>

      <div className="flex min-h-[80px] flex-col gap-2">
        {applications.length === 0 && (
          <p className="rounded-lg border border-dashed border-slate-300 p-3 text-center text-xs text-slate-400">
            کارتی در این مرحله نیست
          </p>
        )}
        {applications.map((application) => (
          <ApplicationCard
            key={application.application_id}
            application={application}
            isDragging={draggedApplicationId === application.application_id}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
          />
        ))}
      </div>
    </div>
  );
}
