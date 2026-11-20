import {object,text} from './dossierData';
import {dossierInsights,records,timelineRows} from './dossierInsights';
import {SourceFact} from './StructuredResumePanel';

export function DossierOverview({parsed,processing,accountName}:{parsed:unknown;processing:unknown;accountName:string}) {
  const d=dossierInsights(parsed,processing,accountName);
  return <section className="editorial-panel" aria-label="خلاصه و کیفیت پرونده">
    <h3 className="text-heading">خلاصه و کیفیت پرونده</h3>
    <p className="mt-3 text-caption text-muted">ذخیره‌شدن تحلیل با تأیید صحت آن متفاوت است. وضعیت زیر فقط وجود داده در فایل را نشان می‌دهد؛ نبود داده، ناتوانی کارجو نیست.</p>
    {!!d.warnings.length&&<ul aria-label="موارد اولویت‌دار بررسی" className="my-4 space-y-2 border-s-2 border-amber-600 ps-3 text-caption">{d.warnings.map((w,i)=><li key={i}>{w.message}</li>)}</ul>}
    <dl className="my-4 grid grid-cols-2 gap-3 text-caption md:grid-cols-3">{d.sections.map(([name,present])=><div key={name}><dt className="text-muted">{name}</dt><dd>{present?'داده موجود است':'داده ثبت نشده'}</dd></div>)}</dl>
    <div className="grid min-w-0 gap-4 md:grid-cols-3">{[['شرط‌های دارای شاهد',d.met],['ناسازگاری‌های اظهارشده',d.unmet],['نیازمند روشن‌شدن',d.unknown]].map(([label,rows])=><section key={label as string} className="min-w-0 border-t border-rule pt-3"><h4 className="font-medium">{label as string}</h4><ul className="mt-2 space-y-2 text-caption">{(rows as Record<string,unknown>[]).slice(0,5).map((r,i)=><li key={i} dir="auto" className="break-words">{text(r.text)}</li>)}</ul>{!(rows as unknown[]).length&&<p className="mt-2 text-caption text-muted">موردی در دادهٔ دریافتی ثبت نشده است.</p>}</section>)}</div>
  </section>;
}

export function DossierTimeline({structured}:{structured:unknown}) {
  const s=object(structured),rows=timelineRows(records(s.activities));
  return <section className="editorial-panel" aria-label="خط زمانی فعالیت‌ها"><h3 className="text-heading">خط زمانی فعالیت‌ها</h3>
    <p className="mt-2 text-caption text-muted">جدیدترین شروعِ مستند در ابتداست. تاریخ‌های ناقص با همان دقت فایل نگه داشته شده‌اند؛ بازهٔ مجهول روی نمودار حدس زده نمی‌شود.</p>
    {!rows.length&&<p className="mt-3 text-caption text-muted">فعالیت مستندی برای نمایش موجود نیست.</p>}
    <ol className="mt-4 space-y-4">{rows.map((r,i)=>{const fields=object(r.fields),dates=object(r.dates);return <li key={text(r.id)||i} className="border-s border-rule ps-4">
      <h4 className="font-medium" dir="auto">{text(object(fields.job_title||fields.project_name).value)||'عنوان نامشخص'}</h4>
      <p className="text-caption text-muted">{({employment:'استخدام',internship:'کارآموزی',freelance:'فریلنس',volunteering:'داوطلبی',project:'پروژه',teaching:'تدریس'} as Record<string,string>)[text(r.kind)]||'نوع نامشخص'}</p>
      <SourceFact label="بازهٔ منبع" value={fields.duration}/>
      {r.dated?<details className="text-caption text-muted"><summary className="cursor-pointer">کران بیرونی بازه در تقویم میلادی؛ روز دقیق ادعا نمی‌شود</summary><p dir="ltr">{r.start} — {dates.ongoing?'اکنون':r.end}</p></details>:<p className="text-caption text-muted">تاریخ نامشخص یا نامعتبر؛ مدت به جمع سابقه افزوده نشده است.</p>}
    </li>})}</ol>
    {!!records(s.overlaps).length&&<p className="mt-3 text-caption">{records(s.overlaps).length.toLocaleString('fa-IR')} هم‌پوشانی ثبت شده؛ همکاری هم‌زمان ممکن است و به‌خودی‌خود خطا نیست.</p>}
    <ul className="mt-2 space-y-2 text-caption text-muted">{records(s.overlaps).map((overlap,i)=>{const ids=Array.isArray(overlap.activities)?overlap.activities:[];const names=rows.filter(r=>ids.includes(r.id)).map(r=>text(object(object(r.fields).job_title||object(r.fields).project_name).value)||'عنوان نامشخص');return <li key={i}><bdi>{names.join(' / ')}</bdi> — {overlap.status==='source_confirmed'?'هم‌پوشانی در کران قطعی تاریخ‌ها':'هم‌پوشانی احتمالی با توجه به دقت تاریخ‌ها'}</li>})}</ul>
    {!!records(s.gaps).length&&<p className="mt-3 text-caption">بازهٔ بدون فعالیت ثبت‌شده وجود دارد؛ ممکن است رزومه ناقص باشد و این موضوع جریمهٔ خودکار ندارد.</p>}
  </section>;
}

export function SkillActivityMatrix({parsed}:{parsed:unknown}) {
  const data=object(parsed),analysis=object(data._evidence_analysis),activities=records(object(data.structured).activities),skills=records(analysis.skills);
  return <section className="editorial-panel" aria-label="ارتباط مهارت و سابقه"><h3 className="text-heading">ارتباط مهارت و سابقه</h3>
    <p className="mt-2 text-caption text-muted">هر ردیف، زمینهٔ ذکر مهارت را نشان می‌دهد؛ مدت شغل به معنی مدت کار با آن مهارت نیست.</p>
    {skills.length?<ul className="mt-4 grid min-w-0 gap-4 md:grid-cols-2">{skills.map((skill,i)=>{const ids=new Set(records(skill.observations).filter(r=>!r.inferred_from&&!r.negated).map(r=>text(r.activity_id)));const linked=activities.filter(a=>ids.has(text(a.id)));return <li key={i} className="min-w-0 break-words border-s border-rule ps-3 text-caption"><bdi className="font-medium">{text(skill.name)}</bdi><ul>{linked.map(a=><li key={text(a.id)} dir="auto">{text(object(object(a.fields).job_title||object(a.fields).project_name).value)||'فعالیت بدون عنوان'}</li>)}</ul>{!linked.length&&<p className="text-muted">ارتباط مستند با فعالیت مشخص نشده است؛ اشارهٔ مهارت یا استنباط جای تجربهٔ عملی نیست.</p>}</li>})}</ul>:<p className="mt-3 text-caption text-muted">ماتریس مستند در دادهٔ دریافتی موجود نیست.</p>}
  </section>;
}

export function InterviewChecklist({parsed,processing,accountName}:{parsed:unknown;processing:unknown;accountName:string}) {
  const d=dossierInsights(parsed,processing,accountName);
  return <section className="editorial-panel" aria-label="راهنمای بررسی و مصاحبه"><h3 className="text-heading">راهنمای بررسی و مصاحبه</h3><p className="mt-2 text-caption text-muted">پرسش‌ها از ابهام‌ها و ادعاهای همین پرونده ساخته شده‌اند؛ سنجش شخصیت یا تصمیم استخدام نیستند.</p>
    <ol className="mt-4 list-inside list-decimal space-y-3 text-body">{d.questions.map((q,i)=><li key={i} className="break-words">{q}</li>)}</ol>{!d.questions.length&&<p className="mt-3 text-caption text-muted">دادهٔ کافی برای سؤال اختصاصی در دسترس نیست.</p>}
    <fieldset className="mt-5 space-y-3 text-caption"><legend className="mb-2 font-medium">چک‌لیست این نوبت بررسی</legend>{['هویت حساب و فایل را تطبیق دادم','منبع سوابق و تاریخ‌ها را بررسی کردم','شروط نامشخص و شواهد مهارت را مرور کردم','سهم فرد و روش اندازه‌گیری دستاوردها را پرسیدم'].map(label=><label key={label} className="flex items-start gap-2"><input type="checkbox" className="mt-1 shrink-0"/>{label}</label>)}</fieldset>
    <p className="mt-3 text-caption text-muted">تیک‌ها فقط برای همین پنجره‌اند و ذخیرهٔ تأیید انسانی یا تغییر وضعیت استخدام محسوب نمی‌شوند.</p>
  </section>;
}
