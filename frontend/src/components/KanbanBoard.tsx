import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import KanbanColumn from "./KanbanColumn";
import { allowedDestinations, STATUS_COLUMNS } from "../types/application";
import { useAppSelector } from "../store/hooks";
import type { ApplicationListItem, ApplicationStatus } from "../types/application";
import { fetchApplicationsForJob, updateApplicationStatus } from "../services/applicationsApi";
import { ApiError } from "../services/apiClient";

interface KanbanBoardProps {
  jobId: string;
}

export default function KanbanBoard({ jobId }: KanbanBoardProps) {
  const queryClient = useQueryClient();
  const [draggedApplication, setDraggedApplication] = useState<ApplicationListItem | null>(null);
  const canManage = useAppSelector(state => ["Admin", "HR_Manager"].includes(state.auth.user?.role ?? ""));
  const board = useRef<HTMLDivElement>(null);
  const instructions = useId();
  const busy = useRef(false);
  const restore = useRef<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [choice, setChoice] = useState<{id:string; target:ApplicationStatus} | null>(null);
  const label = (status: ApplicationStatus) => STATUS_COLUMNS.find(column => column.value === status)?.label ?? status;

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

  function focusCard(id: string) {
    const element = Array.from(board.current?.querySelectorAll<HTMLButtonElement>('[data-move-id]') ?? []).find(button => button.dataset.moveId === id);
    (element ?? board.current)?.focus();
    element?.scrollIntoView?.({block:"nearest",inline:"nearest"});
  }
  useLayoutEffect(() => {
    if (restore.current) {
      if (document.activeElement === document.body || board.current?.contains(document.activeElement)) focusCard(restore.current);
      restore.current = null;
    }
  }, [applications]);
  useEffect(() => { setChoice(null); setAnnouncement(""); }, [jobId]);

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
      const original = context?.previousApplications?.find(item => item.application_id === _variables.applicationId);
      restore.current = _variables.applicationId;
      if (context?.previousApplications) {
        queryClient.setQueryData(applicationsQueryKey, context.previousApplications);
      }
      const rawMessage = error instanceof ApiError ? error.message : "خطا در ارتباط با سرور";
      const friendlyMessage =
        rawMessage === "Business Logic Violation"
          ? "این جابه‌جایی طبق قوانین ماشین وضعیت مجاز نیست."
          : rawMessage;
      setAnnouncement(`انتقال ${original?.candidate_name ?? "کارجو"} به ${label(_variables.newStatus)} ناموفق بود؛ وضعیت ${label(original?.current_status ?? _variables.currentStatus)} بازگردانده شد. ${friendlyMessage}`);
    },
    onSuccess: (_result, variables, context) => {
      const name = context?.previousApplications?.find(item => item.application_id === variables.applicationId)?.candidate_name ?? "کارجو";
      setAnnouncement(`وضعیت ${name} با موفقیت به ${label(variables.newStatus)} تغییر کرد.`);
    },
    // در هر دو حالت، داده را با نسخه‌ی واقعی سرور همگام می‌کنیم
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: applicationsQueryKey });
      busy.current = false;
    },
  });

  function move(application: ApplicationListItem, target: ApplicationStatus) {
    if (busy.current || !canManage) return;
    if (!allowedDestinations(application.current_status).includes(target)) {
      setAnnouncement(`انتقال ${application.candidate_name} به ${label(target)} طبق قوانین مجاز نیست.`); return;
    }
    busy.current = true;
    restore.current = application.application_id;
    setChoice(null);
    setAnnouncement(`در حال انتقال ${application.candidate_name} به ${label(target)}؛ منتظر تأیید سرور باشید.`);
    statusMutation.mutate({applicationId:application.application_id,currentStatus:application.current_status,newStatus:target});
  }
  function activate(application: ApplicationListItem) {
    if (busy.current) return;
    if (choice?.id === application.application_id) { move(application, choice.target); return; }
    const targets = canManage ? allowedDestinations(application.current_status) : [];
    if (!targets.length) { setAnnouncement(`تغییر وضعیت ${application.candidate_name} در این حالت یا با نقش شما مجاز نیست.`); return; }
    setChoice({id:application.application_id,target:targets[0]});
    setAnnouncement(`مقصد ${application.candidate_name}: ${label(targets[0])}؛ برای تأیید Enter و برای انصراف Escape را بزنید.`);
  }
  function navigate(event: KeyboardEvent<HTMLButtonElement>, application: ApplicationListItem) {
    if (choice?.id === application.application_id) {
      if (event.key === "Escape") { event.preventDefault(); setChoice(null); setAnnouncement(`انتقال ${application.candidate_name} لغو شد.`); return; }
      if (["Enter", " "].includes(event.key)) { event.preventDefault(); activate(application); return; }
      if (event.key.startsWith("Arrow")) {
        event.preventDefault();
        const targets = allowedDestinations(application.current_status);
        const direction = ["ArrowLeft","ArrowDown"].includes(event.key) ? 1 : -1;
        const target = targets[(targets.indexOf(choice.target)+direction+targets.length)%targets.length];
        setChoice({...choice,target});
        setAnnouncement(`مقصد ${application.candidate_name}: ${label(target)}؛ هنوز ثبت نشده است.`);
      }
      return;
    }
    if (!event.key.startsWith("Arrow")) return;
    event.preventDefault();
    const column = STATUS_COLUMNS.findIndex(item => item.value === application.current_status);
    const cards = applicationsByStatus.get(application.current_status) ?? [];
    const index = cards.findIndex(item => item.application_id === application.application_id);
    if (["ArrowDown","ArrowUp"].includes(event.key)) {
      const next = cards[index + (event.key === "ArrowDown" ? 1 : -1)];
      if (next) focusCard(next.application_id);
    } else {
      const step = event.key === "ArrowLeft" ? 1 : -1;
      for (let next=column+step;next>=0&&next<STATUS_COLUMNS.length;next+=step) {
        const list = applicationsByStatus.get(STATUS_COLUMNS[next].value) ?? [];
        if (list.length) { focusCard(list[Math.min(index,list.length-1)].application_id); break; }
      }
    }
  }

  function handleDragStart(_event: DragEvent<HTMLDivElement>, application: ApplicationListItem) {
    if (!canManage || busy.current) { _event.preventDefault(); return; }
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

    const application = applications.find(item => item.application_id === applicationId);
    if (application) move(application, targetStatus);
  }

  if (!jobId) {
    return (
      <p className="rounded-lg border border-dashed border-slate-500 dark:border-slate-500 p-6 text-center text-sm text-slate-600 dark:text-slate-300">
        برای مشاهده‌ی بورد، ابتدا یک آگهی شغلی انتخاب کنید.
      </p>
    );
  }

  if (isLoading) {
    return <p className="p-6 text-center text-sm text-slate-600 dark:text-slate-300">در حال بارگذاری بورد...</p>;
  }

  if (isError) {
    return (
      <p className="rounded-lg border border-red-200 dark:border-red-400 bg-red-50 dark:bg-red-950 p-6 text-center text-sm text-red-600 dark:text-red-300">
        خطا در دریافت لیست درخواست‌ها. اتصال به سرور را بررسی کنید.
      </p>
    );
  }

  return (
    <>
    <p id={instructions} className="mb-4 text-caption text-muted">روی کنترل تغییر وضعیت: بالا و پایین برای کارت‌های همان ستون، چپ برای ستون بعدی و راست برای قبلی. Enter یا فاصله برای انتخاب مقصد؛ جهت‌ها برای تغییر مقصد، Enter یا فاصله برای تأیید و Escape برای انصراف. مشاهدهٔ پرونده دکمهٔ جداگانه دارد.</p>
    <p role="status" aria-live="polite" aria-atomic="true" className="mb-3 text-sm text-ink">{announcement}</p>
    <div ref={board} role="region" data-testid="kanban-board" aria-describedby={instructions} aria-label="مراحل استخدام؛ برای دیدن مراحل بیشتر افقی پیمایش کنید" tabIndex={0} className="flex max-w-full min-w-0 items-start gap-3 overflow-x-auto overscroll-x-contain pb-5">
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
          cardControls={application => ({canDrag:canManage && !statusMutation.isPending, moveLabel:choice?.id === application.application_id ? `مقصد: ${label(choice.target)}؛ تأیید با Enter` : undefined,
            moveControl:{'data-move-id':application.application_id, 'aria-label':choice?.id === application.application_id ? `مقصد: ${label(choice.target)}؛ تأیید با Enter؛ ${application.candidate_name}` : `تغییر وضعیت ${application.candidate_name}؛ ${label(application.current_status)}`, 'aria-describedby':instructions,
              'aria-disabled':!canManage || statusMutation.isPending || allowedDestinations(application.current_status).length===0,
              'aria-pressed':choice?.id===application.application_id,
              onClick:()=>activate(application),onKeyDown:event=>navigate(event,application)}})}
        />
      ))}
    </div>
    </>
  );
}
