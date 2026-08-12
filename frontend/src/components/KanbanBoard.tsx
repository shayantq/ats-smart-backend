import { useMemo, useState, type DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import KanbanColumn from "./KanbanColumn";
import { STATUS_COLUMNS } from "../types/application";
import type { ApplicationListItem, ApplicationStatus } from "../types/application";
import { fetchApplicationsForJob, updateApplicationStatus } from "../services/applicationsApi";
import { ApiError } from "../services/apiClient";
import { useToast } from "../context/ToastContext";

interface KanbanBoardProps {
  jobId: string;
}

export default function KanbanBoard({ jobId }: KanbanBoardProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [draggedApplication, setDraggedApplication] = useState<ApplicationListItem | null>(null);

  const applicationsQueryKey = ["applications", jobId];

  const {
    data: applications = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: applicationsQueryKey,
    queryFn: () => fetchApplicationsForJob(jobId),
    enabled: Boolean(jobId),
  });

  // گروه‌بندی کارت‌ها بر اساس ستون (وضعیت فعلی)، همگام با ترتیب STATUS_COLUMNS
  const applicationsByStatus = useMemo(() => {
    const grouped = new Map<ApplicationStatus, ApplicationListItem[]>();
    STATUS_COLUMNS.forEach((column) => grouped.set(column.value, []));
    applications.forEach((application) => {
      grouped.get(application.current_status)?.push(application);
    });
    return grouped;
  }, [applications]);

  const statusMutation = useMutation({
    mutationFn: updateApplicationStatus,
    // جابه‌جایی فوری کارت روی صفحه، پیش از دریافت پاسخ سرور (برای حس واکنش‌گرا)
    onMutate: async ({ applicationId, newStatus }) => {
      await queryClient.cancelQueries({ queryKey: applicationsQueryKey });
      const previousApplications = queryClient.getQueryData<ApplicationListItem[]>(applicationsQueryKey);

      queryClient.setQueryData<ApplicationListItem[]>(applicationsQueryKey, (old) =>
        (old ?? []).map((application) =>
          application.application_id === applicationId
            ? { ...application, current_status: newStatus }
            : application,
        ),
      );

      return { previousApplications };
    },
    // پرش غیرمجاز (400) یا هر خطای دیگر: کارت به ستون مبدا برمی‌گردد (Snap Back)
    onError: (error, _variables, context) => {
      if (context?.previousApplications) {
        queryClient.setQueryData(applicationsQueryKey, context.previousApplications);
      }
      const rawMessage = error instanceof ApiError ? error.message : "خطا در ارتباط با سرور";
      const friendlyMessage =
        rawMessage === "Business Logic Violation"
          ? "این جابه‌جایی طبق قوانین ماشین وضعیت مجاز نیست."
          : rawMessage;
      showToast(friendlyMessage, "error");
    },
    onSuccess: () => {
      showToast("وضعیت کارجو با موفقیت به‌روزرسانی شد.", "success");
    },
    // در هر دو حالت، داده را با نسخه‌ی واقعی سرور همگام می‌کنیم
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: applicationsQueryKey });
    },
  });

  function handleDragStart(_event: DragEvent<HTMLDivElement>, application: ApplicationListItem) {
    setDraggedApplication(application);
  }

  function handleDragEnd() {
    setDraggedApplication(null);
  }

  function handleDropOnColumn(targetStatus: ApplicationStatus) {
    if (!draggedApplication) return;

    const { application_id: applicationId, current_status: sourceStatus } = draggedApplication;
    setDraggedApplication(null);

    // رها کردن روی همان ستون مبدا: کاری انجام نمی‌شود
    if (sourceStatus === targetStatus) return;

    statusMutation.mutate({
      applicationId,
      currentStatus: sourceStatus,
      newStatus: targetStatus,
    });
  }

  if (!jobId) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        برای مشاهده‌ی بورد، ابتدا شناسه‌ی یک آگهی شغلی را وارد کنید.
      </p>
    );
  }

  if (isLoading) {
    return <p className="p-6 text-center text-sm text-slate-500">در حال بارگذاری بورد...</p>;
  }

  if (isError) {
    return (
      <p className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-600">
        خطا در دریافت لیست درخواست‌ها. توکن دسترسی، شناسه‌ی آگهی و روشن بودن سرور بک‌اند را بررسی کنید.
      </p>
    );
  }

  return (
    <div className="flex gap-4 overflow-x-auto pb-4">
      {STATUS_COLUMNS.map((column) => (
        <KanbanColumn
          key={column.value}
          status={column.value}
          label={column.label}
          applications={applicationsByStatus.get(column.value) ?? []}
          draggedApplicationId={draggedApplication?.application_id ?? null}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDropOnColumn={handleDropOnColumn}
        />
      ))}
    </div>
  );
}
