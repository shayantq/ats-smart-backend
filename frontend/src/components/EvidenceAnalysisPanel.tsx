import {object,text} from './dossierData';
import {SourceFact} from './StructuredResumePanel';

const list=(v:unknown):Record<string,unknown>[]=>Array.isArray(v)?v.map(object):[];
const states:Record<string,string>={met:'دارای شاهد صریح',unmet:'اظهار صریح نداشتن',unknown:'نامشخص؛ نیازمند بررسی'};
function RequirementTree({value,depth=0}:{value:unknown;depth?:number}) {
  const node=object(value);
  if(depth>16)return null;
  return <li className="my-2 border-s border-rule ps-3">{text(node.skill)|| (node.operator==='and'?'همهٔ شروط زیر':'حداقل یکی از شروط زیر')} — {states[text(node.status)]||states.unknown}
    {!!list(node.children).length&&<ul>{list(node.children).map((child,i)=><RequirementTree key={i} value={child} depth={depth+1}/>)}</ul>}
  </li>;
}

export default function EvidenceAnalysisPanel({value}:{value:unknown}) {
  const data=object(value);
  if(!['evidence-analysis-v1','evidence-analysis-v2','evidence-analysis-v2.1'].includes(text(data.version)))return null;
  const coverage=object(data.coverage);
  return <section className="editorial-panel min-w-0" aria-label="تحلیل مستند مهارت و شرایط آگهی">
    <h3 className="text-heading">تحلیل مستند مهارت و شرایط آگهی</h3>
    <p className="my-3 text-caption text-muted">نبود شاهد به معنی نداشتن مهارت نیست. این تحلیل کالیبره نشده و تصمیم استخدام نیست.</p>
    {typeof coverage.lower==='number'&&typeof coverage.upper==='number'&&<p className="text-caption">پوشش شروط ضروری با وزن برابر: {coverage.lower.toLocaleString('fa-IR')} تا {coverage.upper.toLocaleString('fa-IR')} درصد؛ حد بالا شامل شروط نامشخص است.</p>}
    <div className="mt-4 grid min-w-0 gap-6 md:grid-cols-2">
      <div className="min-w-0"><h4 className="font-medium">مهارت و منبع</h4>
        {list(data.skills).map(skill=><details key={text(skill.name)} className="my-3 break-words text-caption"><summary className="cursor-pointer"><bdi>{text(skill.name)}</bdi> — {skill.basis==='explicit'?'ذکر صریح':skill.basis==='negated'?'اظهار منفی':skill.basis==='learning'?'در حال یادگیری؛ تجربه اثبات نشده':'استنباط از مهارت مرتبط'}{skill.conflict?'؛ شواهد متناقض':''}</summary>
          {list(skill.observations).map((ref,i)=><div key={i} className="border-s border-rule ps-3"><p>{ref.usage==='practical_claim'?'ادعای کاربرد در فعالیت':ref.context==='certifications'?'اشاره در گواهی‌نامه؛ تجربهٔ عملی اثبات نمی‌شود':'اشاره در متن'}</p><SourceFact label="شاهد مهارت" value={{value:text(skill.name),status:'attributed',evidence:ref.evidence}}/>{typeof ref.claimed_years==='number'&&<p>مدت خوداظهاری‌شده: {ref.claimed_years.toLocaleString('fa-IR')} سال؛ مستقلاً تأیید نشده است.</p>}{Array.isArray(ref.versions)&&!!ref.versions.length&&<p>نسخهٔ ذکرشده: <bdi>{ref.versions.filter(x=>typeof x==='string').join('، ')}</bdi></p>}</div>)}
          {list(skill.last_used).map((claim,i)=><SourceFact key={i} label="آخرین استفادهٔ خوداظهاری‌شده" value={claim}/>)}
          <p className="text-muted">مدت و آخرین استفادهٔ دقیق از این مهارت مستقلاً تأیید نشده است؛ تاریخ شغل جایگزین تاریخ استفادهٔ مهارت نمی‌شود.</p>
        </details>)}
      </div>
      <div className="min-w-0"><h4 className="font-medium">شرایط آگهی</h4>
        {list(data.requirements).length?list(data.requirements).map((r,i)=><div key={i} className="my-3 break-words border-s border-rule ps-3 text-caption"><p dir="auto">{text(r.text)}</p><p>{r.priority==='preferred'?'ترجیحی':'ضروری'} — {states[text(r.status)]||states.unknown}</p>{r.reason==='conflicting_job_requirements'&&<p role="status">شروط آگهی متناقض‌اند؛ نتیجه تا اصلاح آگهی قطعی نیست.</p>}<details><summary className="cursor-pointer">شواهد تطبیق شرط</summary>{!!r.expression&&<ul><RequirementTree value={r.expression}/></ul>}{list(r.evidence).map((e,j)=><p key={j} dir="auto" className="reading-copy">{text(e.text)}</p>)}{!list(r.evidence).length&&<p>شاهد کافی ثبت نشده است.</p>}</details></div>):<p className="text-caption text-muted">شرط ساختاریافته یا صریحی برای ارزیابی دریافت نشده است.</p>}
      </div>
    </div>
    {(!!list(data.career).length||!!list(data.transitions).length)&&<section className="mt-5 min-w-0"><h4 className="font-medium">مسیر شغلی و مسئولیت‌ها</h4>
      {list(data.career).map((c,i)=><div key={i} className="my-3 border-s border-rule ps-3 text-caption">
        <SourceFact label="عنوان ثبت‌شده" value={c.title}/>
        <p>سطح اعلام‌شده: <bdi>{text(c.declared_level)||'نامشخص'}</bdi>؛ سطح تخصص مستقلاً تأیید نشده است.</p>
        {list(c.industry).map((industry,j)=><SourceFact key={j} label="حوزهٔ اعلام‌شده" value={{...industry,status:'attributed'}}/>)}
        {list(c.leadership_signals).map((signal,j)=><SourceFact key={j} label="مسئولیت / ارتقای ادعایی" value={signal.claim}/>)}
      </div>)}
      {list(data.transitions).map((t,i)=><p key={i} className="my-2 text-caption text-muted">{t.kind==='same_employer_role_change'?'تغییر سمت در یک شرکت ثبت شده است؛ ارتقا از این تغییر به‌تنهایی اثبات نمی‌شود.':'عنوان‌ها نشان‌دهندهٔ تغییر خانوادهٔ نقش هستند؛ قابل بررسی با کارجو.'}</p>)}
    </section>}
    {!!list(data.achievements).length&&<section className="mt-5"><h4 className="font-medium">دستاوردهای اعلام‌شده</h4>{list(data.achievements).map((a,i)=><div key={i} className="my-3 border-s border-rule ps-3"><SourceFact label="دستاورد؛ صحت عدد بررسی نشده" value={a.claim}/><p className="text-caption text-muted">{a.individual_contribution==='team_claim'?'نتیجه به تیم نسبت داده شده؛ سهم فرد مشخص نشده است.':a.individual_contribution==='individual_claim'?'سهم فرد در متن ادعا شده و تأیید مستقل ندارد.':'سهم فرد و تیم مشخص نیست.'}</p></div>)}</section>}
    {!!list(data.projects).length&&<section className="mt-5"><h4 className="font-medium">شواهد پروژه‌ها</h4>{list(data.projects).map((p,i)=><div key={i} className="my-3 border-s border-rule ps-3"><SourceFact label="پروژه" value={p.title}/><p className="break-words text-caption" dir="auto">{Array.isArray(p.technologies)?p.technologies.filter(x=>typeof x==='string').join('، '):''}</p>{!!p.duplicate_of&&<p className="text-caption text-muted">پروژهٔ احتمالاً تکراری؛ پیش از شمارش جداگانه بررسی شود.</p>}</div>)}</section>}
    <p className="mt-4 text-caption text-muted">عنوان ارشدیت، دستاورد عددی و سابقه، ادعای رزومه‌اند؛ صرف تعداد سال‌ها سطح تخصص یا نقش فرد در نتیجهٔ تیم را اثبات نمی‌کند.</p>
  </section>;
}
