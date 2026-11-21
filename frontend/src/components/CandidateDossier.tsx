import { lazy, Suspense, useEffect, useId, useRef, useState } from "react";
import { useQuery,useQueryClient } from "@tanstack/react-query";
import { fetchApplicationDossier } from "../services/applicationsApi";
import { dossierData, object, text } from "./dossierData";
import ResumeProcessingStatus from "./ResumeProcessingStatus";
import ExtractionNotice from "./ExtractionNotice";
import StructuredResumePanel, {SourceFact} from "./StructuredResumePanel";
import EvidenceAnalysisPanel from "./EvidenceAnalysisPanel";
import {EvidenceProvider} from './EvidenceContext';
import DocumentEvidencePane from './DocumentEvidencePane';
import {DossierOverview,DossierTimeline,SkillActivityMatrix,InterviewChecklist} from './DossierReview';
import DossierHumanReview from './DossierHumanReview';
import {getDossierReview} from '../services/dossierReviewApi';
import { STATUS_COLUMNS, type ApplicationListItem } from "../types/application";

interface CandidateDossierProps {
  application: ApplicationListItem;
  onClose: () => void;
}
const CandidateRadar = lazy(() => import("./CandidateRadar"));

/** پروندهٔ HR فقط از قرارداد واقعی کارت استفاده می‌کند؛ دادهٔ دریافت‌نشده حدس زده نمی‌شود. */
export default function CandidateDossier({ application, onClose }: CandidateDossierProps) {
  const [identityHidden,setIdentityHidden]=useState(false);
  const queryClient=useQueryClient();
  const query = useQuery({
    queryKey:["application-dossier",application.application_id],
    queryFn:()=>fetchApplicationDossier(application.application_id), retry:false,
    refetchInterval: (query) => {
      const status = query.state.data?.processing_state?.status;
      return query.state.error || query.state.dataUpdateCount >= 120 || !status || ["failed", "succeeded"].includes(status) ? false : 5000;
    },
    refetchIntervalInBackground: false,
  });
  const processing = query.data?.processing_state;
  const human=useQuery({queryKey:['dossier-review',application.application_id],queryFn:()=>getDossierReview(application.application_id),enabled:!!query.data?.resume_id,retry:false,refetchInterval:q=>q.state.dataUpdateCount>=120?false:15000,refetchIntervalInBackground:false});
  useEffect(()=>{if(query.data?.resume_id){void queryClient.invalidateQueries({queryKey:['dossier-review',application.application_id]});void queryClient.invalidateQueries({queryKey:['dossier-versions',application.application_id]});}},[query.dataUpdatedAt,queryClient,application.application_id,query.data?.resume_id]);
  const reviewState=human.dataUpdatedAt>=query.dataUpdatedAt?human.data:undefined;
  const parsed=reviewState?.effective_parsed??query.data?.parsed_data;
  const detail = dossierData(query.data?{...query.data,parsed_data:parsed||null}:undefined);
  const matchingScore = object(query.data?.agent_analysis?.matching).score;
  const score = typeof matchingScore === "number" && Number.isFinite(matchingScore) ? matchingScore : application.score_ai;
  const flags = query.data?.agent_analysis?.flags;
  const flagCodes = Array.isArray(flags) ? flags.map(flag => object(flag).code) : [];
  const evidenceVerified = flagCodes.includes("MODEL_EVIDENCE_VERIFIED");
  const evidenceLimited = flagCodes.includes("MODEL_EVIDENCE_BUDGET_LIMITED");
  const reviewReason = flagCodes.includes("MODEL_SCORE_EVIDENCE_INCOMPLETE") ? "incomplete_input"
    : flagCodes.includes("MODEL_MATCHING_EVIDENCE_CONFLICT") ? "matching_conflict" : undefined;
  const scoreBlocked = (!!processing?.status && processing.status !== 'succeeded') || object(parsed?._extraction).status === 'partial'||!!parsed?._review_warning;
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
      else document.querySelector<HTMLElement>('[role="tabpanel"], #main-content')?.focus();
    };
  }, [application.application_id]);

  return (
    <EvidenceProvider key={application.application_id}><dialog ref={dialog} aria-labelledby={title} aria-describedby={note} onCancel={(event) => { event.preventDefault(); onClose(); }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]')).filter(control=>control.getClientRects().length>0);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }} className="dossier-dialog" dir="rtl">
      <div className="p-5 sm:p-9 lg:p-12">
        <header className="flex items-start justify-between gap-4 border-b border-rule pb-6">
          <div className="min-w-0">
            <p className="editorial-label">پروندهٔ کارجو / بررسی منابع انسانی</p>
            <h2 id={title} dir="auto" className="mt-3 break-words text-heading sm:text-display">{identityHidden?'مرور بدون نمایش هویت':application.candidate_name}</h2>
            <p className="mt-2 text-caption text-muted">{STATUS_COLUMNS.find((column) => column.value === application.current_status)?.label}</p>
            {!identityHidden&&(text(personal.email) || text(personal.phone)) && <p className="mt-2 break-words text-caption text-muted"><bdi>{text(personal.email)}</bdi> <bdi>{text(personal.phone)}</bdi></p>}
          </div>
          <button type="button" autoFocus onClick={onClose} className="shrink-0 rounded border border-rule px-3 py-2 text-caption hover:bg-wash" aria-label="بستن پرونده">بستن ×</button>
        </header>
        <p id={note} className="my-5 max-w-prose text-caption text-muted">اطلاعات رزومهٔ مرتبط با همین درخواست؛ دادهٔ غایب به معنی نداشتن مهارت یا سابقه نیست.</p>
        <button aria-pressed={identityHidden} onClick={()=>setIdentityHidden(v=>!v)} className="mb-4 rounded border border-rule px-3 py-2 text-caption">{identityHidden?'بازگرداندن نمای کامل پرونده':'پنهان‌کردن اطلاعات هویتی'}</button>
        {identityHidden&&<section className="editorial-panel" aria-label="خلاصه بدون هویت"><h3 className="text-heading">مرور محدود بدون اطلاعات هویتی</h3><p className="my-3 text-caption">نام، تماس، متن، سند، شواهد آزاد و یادداشت‌ها در این نما نشان داده نمی‌شوند. این گزینه فقط نمایش همین پرونده را محدود می‌کند؛ ناشناس‌سازی داده، خروجی قابل اشتراک یا تضمین حذف سوگیری نیست.</p><p className="text-body">تعداد فعالیت‌های ثبت‌شده: {Array.isArray(object(parsed?.structured).activities)?(object(parsed?.structured).activities as unknown[]).length.toLocaleString('fa-IR'):'نامشخص'}</p></section>}
        {query.isPending && <p role="status">در حال دریافت پرونده…</p>}
        <ResumeProcessingStatus state={processing} reviewReason={reviewReason} />
        <ExtractionNotice value={query.data?.parsed_data?._extraction} />
        {query.isError && <div role="alert" className="my-4 border-s-2 border-red-300 dark:border-red-400 ps-4 text-red-800 dark:text-red-300">دریافت جزئیات پرونده ممکن نشد؛ دسترسی و اتصال را بررسی کنید. <button onClick={()=>void query.refetch()} className="underline">تلاش مجدد</button></div>}
        {query.data && !query.data.resume_id && <p role="status" className="my-4 text-caption text-muted">این درخواست قدیمی هنوز به نسخهٔ مشخصی از رزومه متصل نشده است.</p>}
        {!identityHidden&&<>
        {query.data&&<DossierOverview parsed={parsed} processing={processing} accountName={application.candidate_name}/>}
        {!!parsed?._review_warning&&<p role="status" className="my-3 border-s-2 border-amber-600 ps-3 text-caption">اصلاح انسانی اعمال شده است؛ محاسبات و امتیاز قبلی باید با این اصلاح بازبینی شوند.</p>}
        <div className="grid min-w-0 gap-x-8 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="min-w-0">
        <div className="grid min-w-0 gap-x-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <aside className="min-w-0">
            <section className="editorial-panel" aria-labelledby={`${title}-skills`}>
              <h3 id={`${title}-skills`} className="text-heading">مهارت‌ها</h3>
              {detail.skills.length ? <ul className="mt-3 flex flex-wrap gap-2">{detail.skills.map(skill=><li key={skill} dir="auto" className="max-w-full break-words rounded border border-rule px-2 py-1 text-caption">{skill}</li>)}</ul>
                : <p className="mt-3 text-body text-muted">فهرست مهارت‌ها در دادهٔ دریافتی موجود نیست.</p>}
            </section>
            <section className="editorial-panel" aria-labelledby={`${title}-analysis`}>
              <h3 id={`${title}-analysis`} className="text-heading">تحلیل هوش مصنوعی</h3>
              {evidenceLimited && !scoreBlocked ? <p className="mt-3 text-body">به‌دلیل طول رزومه، مدل یک شاهد مهارتی را بررسی کرد. وضعیت همهٔ شرط‌ها در بخش پوشش شروط آگهی آمده است.</p>
                : evidenceVerified && !scoreBlocked ? <p className="mt-3 text-body">مدل حضور مهارت‌های مستند را بررسی کرد. جزئیات را در پوشش شروط آگهی ببینید.</p>
                : <p className="mt-3 text-body">امتیاز ثبت‌شده: <strong className="tabular-nums">{reviewReason ? "نیازمند بازبینی شواهد" : scoreBlocked ? "تا تکمیل تحلیل قابل اتکا نیست" : score === null ? "هنوز محاسبه نشده" : `${score} از ۱۰۰`}</strong></p>}
              <p className="mt-2 text-caption text-muted">امتیاز تطابق، تصمیم نهایی استخدام نیست.</p>
              {!!query.data?.parsed_data?._evidence_analysis&&<p className="mt-2 text-caption text-muted">امتیاز مدل کالیبره نشده است؛ پوشش مستند شروط آگهی جداگانه در پایین پرونده نمایش داده می‌شود.</p>}
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
                {!!entry.fields && <details className="mt-2 text-caption text-muted"><summary className="cursor-pointer">شواهد و وضعیت فیلدهای سابقه</summary>
                  <SourceFact label="سمت" value={object(entry.fields).job_title}/><SourceFact label="سازمان" value={object(entry.fields).company}/>
                  <SourceFact label="تاریخ" value={object(entry.fields).duration}/><SourceFact label="مکان" value={object(entry.fields).location}/>
                  <SourceFact label="نوع همکاری" value={object(entry.fields).engagement_type}/><SourceFact label="مشتری" value={object(entry.fields).client}/>
                  {Array.isArray(entry.claims) && entry.claims.map((claim,index)=><SourceFact key={index} label="مسئولیت / دستاورد اعلام‌شده" value={claim}/>)}
                </details>}
                {entry.is_valid === false && <p className="text-caption text-amber-800 dark:text-amber-300">نیازمند بررسی: {text(entry.flag_reason) || "بازهٔ زمانی تأیید نشده است."}</p>}
              </li>)}</ol> : <p className="reading-copy mt-3 text-muted">سوابق کاری هنوز استخراج نشده است.</p>}
            </section>
          </div>
        </div>
        <StructuredResumePanel value={parsed?.structured} accountName={application.candidate_name} />
        <EvidenceAnalysisPanel value={parsed?._evidence_analysis} />
        {query.data&&<><DossierTimeline structured={parsed?.structured}/><SkillActivityMatrix parsed={parsed}/><InterviewChecklist parsed={parsed} processing={processing} accountName={application.candidate_name}/></>}
        {query.data?.resume_id&&<DossierHumanReview key={application.application_id} applicationId={application.application_id} state={reviewState}/>}
        </div>
        <aside className="min-w-0 xl:sticky xl:top-4 xl:self-start">
          {query.data?.resume_id&&<DocumentEvidencePane applicationId={application.application_id} layout={query.data.parsed_data?._extraction}/>}
        </aside>
        </div>
        <details className="editorial-panel" open={!query.data?.parsed_data?.structured}>
          <summary id={`${title}-resume`} className="cursor-pointer text-heading">متن رزومه</summary>
          <p className="reading-copy mt-3 text-muted" dir="auto">{query.data?.raw_text || "متن رزومه هنوز استخراج نشده است."}</p>
        </details>
        </>}
        <footer className="border-t border-rule pt-5 text-caption text-muted">آخرین به‌روزرسانی: {new Date(application.updated_at).toLocaleDateString("fa-IR")}</footer>
      </div>
    </dialog></EvidenceProvider>
  );
}
