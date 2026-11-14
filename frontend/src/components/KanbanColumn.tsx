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
      role="region"
      aria-label={label}
      data-testid={`kanban-column-${status}`}
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
      className={`flex w-[17rem] shrink-0 flex-col rounded border p-3 transition-colors duration-200 sm:w-[19rem] ${
        isOver ? "border-slate-500 dark:border-slate-500 bg-slate-100 dark:bg-slate-900" : "border-rule bg-wash"
      }`}
    >
      <div className="mb-4 flex items-center justify-between gap-2 border-b border-rule pb-3">
        <h3 className="text-sm font-semibold leading-7 text-ink">{label}</h3>
        <span
          data-testid="column-count"
          className="text-caption tabular-nums text-muted"
        >
          {applications.length}
        </span>
      </div>

      <div className="flex min-h-[80px] flex-col gap-2">
        {applications.length === 0 && (
          <p className="px-2 py-8 text-center text-caption text-muted">
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
