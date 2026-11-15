import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import KanbanColumn from "./KanbanColumn";
import { allowedDestinations, STATUS_COLUMNS } from "../types/application";
import { useAppSelector } from "../store/hooks";
import type { ApplicationListItem, ApplicationStatus, ApplicationListResponse } from "../types/application";
import { updateApplicationStatus } from "../services/applicationsApi";
import { columnKey, useKanbanPages } from "../hooks/useKanbanPages";
import CandidateDossier from "./CandidateDossier";
import { apiRequest } from "../services/apiClient";
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

  const pages = useKanbanPages(jobId);
  const [overrides,setOverrides]=useState<Map<string,ApplicationListItem>>(new Map());
  const [dossier,setDossier]=useState<ApplicationListItem|null>(null);
  const dossierTrigger=useRef<Element|null>(null);
  const columnHandles=useRef(new Map<ApplicationStatus,(id:string)=>void>());
  const counts=useQuery({queryKey:["application-counts",jobId],queryFn:()=>apiRequest<Record<string,number>>('/applications/counts?job_id='+encodeURIComponent(jobId)),enabled:!!jobId});
  const applications=useMemo(()=>{
    const items=new Map<string,ApplicationListItem>();
    pages.forEach(query=>query.data?.pages.forEach(page=>page.items.forEach(item=>items.set(item.application_id,item))));
    overrides.forEach((item,id)=>items.set(id,item));return [...items.values()];
  },[...pages.map(query=>query.data),overrides]);
  const isLoading=applications.length===0 && pages.some(query=>query.isPending && !query.data);
  const isError=pages.some(query=>query.isError && !query.data);
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
    const item=applications.find(item=>item.application_id===id);
    if(item) columnHandles.current.get(item.current_status)?.(id);
    const element = Array.from(board.current?.querySelectorAll<HTMLButtonElement>('[data-move-id]') ?? []).find(button => button.dataset.moveId === id);
    element?.focus();
    element?.scrollIntoView?.({block:"nearest",inline:"nearest"});
  }
  useLayoutEffect(() => {
    if (restore.current) {
      if(!applications.some(item=>item.application_id===restore.current))return;
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
      const original=applications.find(item=>item.application_id===applicationId);
      if(original) setOverrides(previous=>new Map(previous).set(applicationId,{...original,current_status:newStatus}));
      return {original};
    },
    // پرش غیرمجاز (400) یا هر خطای دیگر: کارت به ستون مبدا برمی‌گردد (Snap Back)
    onError: (error, _variables, context) => {
      const original = context?.original;
      restore.current = _variables.applicationId;
      setOverrides(previous=>{const next=new Map(previous);next.delete(_variables.applicationId);return next;});
      const rawMessage = error instanceof ApiError ? error.message : "خطا در ارتباط با سرور";
      const friendlyMessage =
        rawMessage === "Business Logic Violation"
          ? "این جابه‌جایی طبق قوانین ماشین وضعیت مجاز نیست."
          : rawMessage;
      setAnnouncement(`انتقال ${original?.candidate_name ?? "کارجو"} به ${label(_variables.newStatus)} ناموفق بود؛ وضعیت ${label(original?.current_status ?? _variables.currentStatus)} بازگردانده شد. ${friendlyMessage}`);
    },
    onSuccess: (_result, variables, context) => {
      const name = context?.original?.candidate_name ?? "کارجو";
      setAnnouncement(`وضعیت ${name} با موفقیت به ${label(variables.newStatus)} تغییر کرد.`);
    },
    // در هر دو حالت، داده را با نسخه‌ی واقعی سرور همگام می‌کنیم
    onSettled: async (_data,_error,variables) => {
      restore.current=variables.applicationId;
      await Promise.all([variables.currentStatus,variables.newStatus].map(status=>queryClient.resetQueries({queryKey:columnKey(jobId,status),exact:true})));
      setOverrides(previous=>{const next=new Map(previous);next.delete(variables.applicationId);return next;});
      void queryClient.invalidateQueries({queryKey:["application-counts",jobId]});busy.current=false;
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
      else if(event.key==="ArrowDown") {
        const query=pages[column];
        if(query.hasNextPage) void query.loadMore().then(()=>{
          if((document.activeElement as HTMLElement)?.dataset.moveId!==application.application_id)return;
          const data=queryClient.getQueryData<InfiniteData<ApplicationListResponse>>(columnKey(jobId,application.current_status));
          const all=[...new Map(data?.pages.flatMap(page=>page.items).map(item=>[item.application_id,item])??[]).values()];
          const next=all[all.findIndex(item=>item.application_id===application.application_id)+1];
          if(next)columnHandles.current.get(application.current_status)?.(next.application_id);
        });
      }
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
      <div role="alert" className="border border-red-200 dark:border-red-400 p-6 text-sm text-red-700 dark:text-red-300">
        <p>خطا در دریافت لیست درخواست‌ها. اتصال به سرور را بررسی کنید.</p>
        <button className="mt-3 border border-slate-500 px-3 py-2" onClick={()=>{pages.filter(query=>query.isError).forEach(query=>void query.refetch());}}>تلاش مجدد</button>
      </div>
    );
  }

  return (
    <>
    <p id={instructions} className="mb-4 text-caption text-muted">روی کنترل تغییر وضعیت: بالا و پایین برای کارت‌های همان ستون، چپ برای ستون بعدی و راست برای قبلی. Enter یا فاصله برای انتخاب مقصد؛ جهت‌ها برای تغییر مقصد، Enter یا فاصله برای تأیید و Escape برای انصراف. مشاهدهٔ پرونده دکمهٔ جداگانه دارد.</p>
    <p role="status" aria-live="polite" aria-atomic="true" className="mb-3 text-sm text-ink">{announcement}</p>
    <div ref={board} role="region" data-testid="kanban-board" aria-describedby={instructions} aria-label="مراحل استخدام؛ برای دیدن مراحل بیشتر افقی پیمایش کنید" tabIndex={0} className="flex max-w-full min-w-0 items-start gap-3 overflow-x-auto overscroll-x-contain pb-5">
      {STATUS_COLUMNS.map((column,index) => (
        <KanbanColumn
          key={column.value}
          status={column.value}
          total={counts.data?.[column.value]}
          hasMore={pages[index].hasNextPage} fetching={pages[index].isFetchingNextPage} loadError={pages[index].isFetchNextPageError}
          onLoadMore={()=>{void pages[index].loadMore();}}
          registerFocus={handler=>{columnHandles.current.set(column.value,handler);}}
          pinnedIds={[draggedApplication?.application_id,choice?.id,dossier?.application_id].filter((id):id is string=>!!id)}
          label={column.label}
          applications={applicationsByStatus.get(column.value) ?? []}
          draggedApplicationId={draggedApplication?.application_id ?? null}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDropOnColumn={handleDropOnColumn}
          cardControls={application => ({onOpenDossier:()=>{dossierTrigger.current=document.activeElement;setDossier(application);},canDrag:canManage && !statusMutation.isPending, moveLabel:choice?.id === application.application_id ? `مقصد: ${label(choice.target)}؛ تأیید با Enter` : undefined,
            moveControl:{'data-move-id':application.application_id, 'aria-label':choice?.id === application.application_id ? `مقصد: ${label(choice.target)}؛ تأیید با Enter؛ ${application.candidate_name}` : `تغییر وضعیت ${application.candidate_name}؛ ${label(application.current_status)}`, 'aria-describedby':instructions,
              'aria-disabled':!canManage || statusMutation.isPending || allowedDestinations(application.current_status).length===0,
              'aria-pressed':choice?.id===application.application_id,
              onClick:()=>activate(application),onKeyDown:event=>navigate(event,application)}})}
        />
      ))}
    </div>
    {dossier && <CandidateDossier application={dossier} onClose={()=>{setDossier(null);requestAnimationFrame(()=>{if(dossierTrigger.current instanceof HTMLElement && dossierTrigger.current.isConnected)dossierTrigger.current.focus();else focusCard(dossier.application_id);});}} />}
    </>
  );
}
