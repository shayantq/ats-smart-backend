import { lazy, Suspense, useEffect, useId, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchApplicationDossier } from "../services/applicationsApi";
import { dossierData, object, text } from "./dossierData";
import { STATUS_COLUMNS, type ApplicationListItem } from "../types/application";

interface CandidateDossierProps {
  application: ApplicationListItem;
  onClose: () => void;
}
const CandidateRadar = lazy(() => import("./CandidateRadar"));

/** پروندهٔ HR فقط از قرارداد واقعی کارت استفاده می‌کند؛ دادهٔ دریافت‌نشده حدس زده نمی‌شود. */
export default function CandidateDossier({ application, onClose }: CandidateDossierProps) {
  const query = useQuery({queryKey:["application-dossier",application.application_id],queryFn:()=>fetchApplicationDossier(application.application_id),retry:false});
  const detail = dossierData(query.data);
  const personal = object(query.data?.parsed_data?.personal_info);
  const dialog = useRef<HTMLDialogElement>(null);
  // محرک را پیش از autofocus فرزند نگه می‌داریم تا بستن با کیبورد هم فوکوس را برگرداند.
  const trigger = useRef(document.activeElement);
  const title = useId();
  const note = useId();
  useEffect(() => {
    const previous = trigger.current;
    const element = dialog.current;
    const overflow = document.body.style.overflow;
    element?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      element?.close();
      document.body.style.overflow = overflow;
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);

  return (
    <dialog ref={dialog} aria-labelledby={title} aria-describedby={note} onCancel={(event) => { event.preventDefault(); onClose(); }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]');
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }} className="dossier-dialog" dir="rtl">
      <div className="p-5 sm:p-9 lg:p-12">
        <header className="flex items-start justify-between gap-4 border-b border-rule pb-6">
          <div className="min-w-0">
            <p className="editorial-label">پروندهٔ کارجو / بررسی منابع انسانی</p>
            <h2 id={title} dir="auto" className="mt-3 break-words text-heading sm:text-display">{application.candidate_name}</h2>
            <p className="mt-2 text-caption text-muted">{STATUS_COLUMNS.find((column) => column.value === application.current_status)?.label}</p>
            {(text(personal.email) || text(personal.phone)) && <p className="mt-2 break-words text-caption text-muted"><bdi>{text(personal.email)}</bdi> <bdi>{text(personal.phone)}</bdi></p>}
          </div>
          <button type="button" autoFocus onClick={onClose} className="shrink-0 rounded border border-rule px-3 py-2 text-caption hover:bg-wash" aria-label="بستن پرونده">بستن ×</button>
        </header>
        <p id={note} className="my-5 max-w-prose text-caption text-muted">اطلاعات رزومهٔ مرتبط با همین درخواست؛ دادهٔ غایب به معنی نداشتن مهارت یا سابقه نیست.</p>
        {query.isPending && <p role="status">در حال دریافت پرونده…</p>}
        {query.isError && <div role="alert" className="my-4 border-s-2 border-red-300 ps-4 text-red-800">دریافت جزئیات پرونده ممکن نشد؛ دسترسی و اتصال را بررسی کنید. <button onClick={()=>void query.refetch()} className="underline">تلاش مجدد</button></div>}
        {query.data && !query.data.resume_id && <p role="status" className="my-4 text-caption text-muted">این درخواست قدیمی هنوز به نسخهٔ مشخصی از رزومه متصل نشده است.</p>}
        <div className="grid min-w-0 gap-x-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <aside className="min-w-0">
            <section className="editorial-panel" aria-labelledby={`${title}-skills`}>
              <h3 id={`${title}-skills`} className="text-heading">مهارت‌ها</h3>
              {detail.skills.length ? <ul className="mt-3 flex flex-wrap gap-2">{detail.skills.map(skill=><li key={skill} dir="auto" className="max-w-full break-words rounded border border-rule px-2 py-1 text-caption">{skill}</li>)}</ul>
                : <p className="mt-3 text-body text-muted">فهرست مهارت‌ها در دادهٔ دریافتی موجود نیست.</p>}
            </section>
            <section className="editorial-panel" aria-labelledby={`${title}-analysis`}>
              <h3 id={`${title}-analysis`} className="text-heading">تحلیل هوش مصنوعی</h3>
              <p className="mt-3 text-body">امتیاز ثبت‌شده: <strong className="tabular-nums">{application.score_ai === null ? "هنوز محاسبه نشده" : `${application.score_ai} از ۱۰۰`}</strong></p>
              <p className="mt-2 text-caption text-muted">امتیاز تطابق، تصمیم نهایی استخدام نیست.</p>
              {detail.radar.length ? <Suspense fallback={<p role="status">در حال آماده‌سازی نمودار…</p>}><CandidateRadar metrics={detail.radar} /></Suspense> : <div className="mt-5 border-s-2 border-rule ps-4">
                <p className="text-sm font-medium">نمودار رادار در دسترس نیست</p>
                <p className="mt-2 text-caption text-muted">حداقل سه سیگنال معتبر و هم‌مقیاس از عامل مهارت نرم لازم است؛ امتیاز کلی جایگزین آن‌ها نمی‌شود.</p>
              </div>}
            </section>
          </aside>
          <div className="min-w-0">
            <section className="editorial-panel" aria-labelledby={`${title}-history`}>
              <h3 id={`${title}-history`} className="text-heading">سوابق کاری</h3>
              {detail.entries.length ? <ol className="mt-4 space-y-5">{detail.entries.map(entry=><li key={entry.originalIndex} className="border-s border-rule ps-4">
                <h4 className="font-medium">{text(entry.job_title) || "عنوان ثبت نشده"}</h4>
                <p className="text-body" dir="auto">{text(entry.company)}</p>
                <p className="text-caption text-muted" dir="auto">{text(entry.duration)}</p>
                {entry.is_valid === false && <p className="text-caption text-amber-800">نیازمند بررسی: {text(entry.flag_reason) || "بازهٔ زمانی تأیید نشده است."}</p>}
              </li>)}</ol> : <p className="reading-copy mt-3 text-muted">سوابق کاری هنوز استخراج نشده است.</p>}
            </section>
            <section className="editorial-panel" aria-labelledby={`${title}-resume`}>
              <h3 id={`${title}-resume`} className="text-heading">متن رزومه</h3>
              <p className="reading-copy mt-3 text-muted" dir="auto">{query.data?.raw_text || "متن رزومه هنوز استخراج نشده است."}</p>
            </section>
          </div>
        </div>
        <footer className="border-t border-rule pt-5 text-caption text-muted">آخرین به‌روزرسانی: {new Date(application.updated_at).toLocaleDateString("fa-IR")}</footer>
      </div>
    </dialog>
  );
}
