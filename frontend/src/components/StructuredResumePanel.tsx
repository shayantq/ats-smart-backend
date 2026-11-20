import {object,text} from "./dossierData";
import {useEvidence} from './EvidenceContext';

const labels: Record<string,string>={extracted:"از متن رزومه",attributed:"ادعای رزومه",ambiguous:"نیازمند بررسی",missing:"نامشخص",invalid:"نامعتبر"};
const fieldLabels: Record<string,string>={title:"عنوان",institution:"مؤسسه / صادرکننده",date:"تاریخ",language:"زبان",level:"سطح اعلام‌شده",credential_id:"شناسه",expiry:"تاریخ انقضای اعلام‌شده",project_name:"پروژه",job_title:"عنوان فعالیت",company:"سازمان",duration:"بازهٔ زمانی",location:"مکان",client:"مشتری",engagement_type:"نوع همکاری",audience:"مخاطبان"};
const list=(v:unknown):Record<string,unknown>[]=>Array.isArray(v)?v.map(object):[];
const translations:Record<string,string>={persian:"فارسی",farsi:"فارسی",english:"انگلیسی",german:"آلمانی",spanish:"اسپانیایی",french:"فرانسوی",native:"مادری",advanced:"پیشرفته",fluent:"روان",intermediate:"متوسط",'upper intermediate':"متوسط رو به بالا",basic:"پایه",beginner:"مبتدی"};

export function durationLabel(min:number,max:number) {
  if(max<=0)return "مدت قابل محاسبه موجود نیست";
  const a=Math.floor(min*12),b=Math.ceil(max*12);
  return a===b?`حدود ${a.toLocaleString('fa-IR')} ماه`:`حدود ${a.toLocaleString('fa-IR')} تا ${b.toLocaleString('fa-IR')} ماه`;
}
function linkInfo(value:string) {
  try {const u=new URL(/^https?:\/\//i.test(value)?value:`https://${value}`);
    if(!['https:','http:'].includes(u.protocol)||u.username||u.password||!u.hostname.includes('.'))return null;
    const parts=u.pathname.split('/').filter(Boolean),host=u.hostname.toLowerCase().replace(/^www\./,'');
    return {href:u.href,label:host==='github.com'?(parts.length>=2?'مخزن پروژه در گیت‌هاب':'پروفایل گیت‌هاب'):host==='linkedin.com'?'پروفایل لینکدین':'پیوند وب'};
  }catch{return null;}
}

export function SourceFact({label,value}:{label:string;value:unknown}) {
  const evidence=useEvidence();
  const f=object(value),refs=list(f.evidence),raw=text(f.value);
  const display=['زبان','سطح اعلام‌شده'].includes(label)?translations[raw.toLowerCase().replace(/-/g,' ')]||raw:raw;
  return <div className="min-w-0 py-2 text-caption">
    <span className="text-muted">{label}: </span><bdi className="break-words">{display||"نامشخص"}</bdi>
    {(!!raw||['ambiguous','invalid'].includes(text(f.status)))&&<span className="ms-2 text-muted">({f.reason==='human_correction'?'اصلاح ثبت‌شدهٔ کارشناس':labels[text(f.status)]||"نیازمند بررسی"})</span>}
    {!!refs.length && <details className="mt-1 text-muted"><summary className="cursor-pointer rounded-sm focus-visible:outline focus-visible:outline-2">شاهد {label}</summary>
      {refs.map((ref,i)=><div key={i}><p className="reading-copy mt-1 break-words" dir="auto">{typeof ref.page==="number"?`صفحهٔ ${ref.page}: `:""}{text(ref.text)}</p>{evidence&&<button type="button" className="my-1 rounded border border-rule px-2 py-1 text-caption" onClick={()=>evidence.select({text:text(ref.text),page:typeof ref.page==='number'?ref.page:undefined,bbox:Array.isArray(ref.bbox)?ref.bbox as number[]:undefined,block_id:text(ref.block_id)})}>نمایش محل شاهد در سند</button>}</div>)}
    </details>}
  </div>;
}

export default function StructuredResumePanel({value,accountName}:{value:unknown;accountName:string}) {
  const data=object(value);
  if(data.version!=="resume-structured-v1") return null;
  const identity=object(data.identity),name=object(identity.name);
  const different=!!text(name.value) && text(name.value).trim().toLocaleLowerCase()!==accountName.trim().toLocaleLowerCase();
  const groups:[string,Record<string,unknown>[]][]=[
    ["سوابق تدریس",list(data.activities).filter(x=>x.kind==="teaching")],
    ["فعالیت داوطلبانه",list(data.activities).filter(x=>x.kind==="volunteering")],
    ["پروژه‌ها",list(data.activities).filter(x=>x.kind==="project")],
    ["تحصیلات",list(data.education)],["دوره‌ها و گواهی‌نامه‌ها",list(data.certifications)],
    ["زبان‌ها",list(data.languages)],["انتشارات",list(data.publications)],["جوایز",list(data.awards)],
  ];
  const total=object(object(data.totals).total_work);
  return <div className="min-w-0 border-t border-rule py-5">
    <h3 className="text-heading">اطلاعات مستند رزومه</h3>
    <p className="mt-2 text-caption text-muted">این اطلاعات از فایل استخراج شده‌اند؛ اصالت مدرک، سابقه و سطح زبان مستقلاً تأیید نشده است.</p>
    <div className="mt-4 grid min-w-0 gap-x-8 md:grid-cols-2">
      <section className="min-w-0"><h4 className="font-medium">هویت داخل فایل</h4>
        <p className="mt-2 break-words text-caption text-muted">نام حساب: <bdi>{accountName}</bdi></p>
        <SourceFact label="نام داخل رزومه" value={name} /><SourceFact label="مکان" value={identity.location}/>
        {different && <p role="status" className="text-caption text-amber-800 dark:text-amber-300">نام حساب و نام داخل رزومه متفاوت‌اند؛ برای بررسی هویت تطبیق دهید. حساب تغییر نکرده است.</p>}
        {name.status==="ambiguous" && <p role="status" className="text-caption text-amber-800 dark:text-amber-300">چند نام محتمل در فایل دیده شد؛ نام فرد هنوز قطعی نیست.</p>}
      </section>
      <section className="min-w-0"><h4 className="font-medium">تماس و پیوندهای ذکرشده</h4>
        {list(data.contacts).map((f,i)=><SourceFact key={i} label={text(f.value).includes('@')?'ایمیل':'تلفن'} value={f}/>)}
        {list(data.links).map((f,i)=>{const info=linkInfo(text(f.value));return <div key={i}><SourceFact label={info?.label||'پیوند نامعتبر'} value={f}/>{info&&<a href={info.href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" className="text-caption underline">بازکردن {info.label}</a>}</div>})}
        {!!list(data.links).length&&<p className="text-caption text-muted">پیوندها از فایل خوانده شده‌اند؛ تا انتخاب شما باز نمی‌شوند و مالکیتشان تأیید نشده است.</p>}
        {list(data.contacts).some(x=>x.reason==="generic_contact_requires_review")&&<p className="text-caption text-muted">نشانی عمومی مانند help یا support ممکن است متعلق به قالب یا سازمان باشد؛ مالکیت آن بررسی شود.</p>}
      </section>
    </div>
    {typeof total.min_years==="number"&&typeof total.max_years==="number"&&<p className="my-4 text-caption text-muted">سابقهٔ خالص مستند کار، فریلنس و کارآموزی: {durationLabel(total.min_years,total.max_years)}؛ با حفظ عدم قطعیت تاریخ‌ها و حذف هم‌پوشانی. مدت فعالیت بدون تاریخ در این عدد نیست.</p>}
    <dl className="mb-4 flex flex-wrap gap-x-6 gap-y-2 text-caption text-muted">{([['employment','استخدام'],['internship','کارآموزی'],['freelance','فریلنس'],['volunteering','داوطلبی']] as const).map(([key,label])=>{
      const item=object(object(data.totals)[key]);
      return list(data.activities).some(x=>x.kind===key)&&typeof item.min_years==='number'&&typeof item.max_years==='number'?<div key={key}><dt>{label}</dt><dd>{durationLabel(item.min_years,item.max_years)}</dd></div>:null;
    })}</dl>
    <div className="grid min-w-0 gap-x-8 md:grid-cols-2">{groups.map(([label,items])=>!!items.length&&<section key={label} className="editorial-panel min-w-0">
      <h4 className="font-medium">{label}</h4>
      {items.map((item,i)=><div key={i} className="mt-3 border-s border-rule ps-3">
        {Object.entries(object(item.fields)).filter(([key])=>fieldLabels[key]).map(([key,f])=><SourceFact key={key} label={fieldLabels[key]} value={f}/>)}
        {list(item.claims).map((claim,index)=><SourceFact key={index} label="توضیح اعلام‌شده" value={claim}/>)}
        {item.expiry_status==="expired_claim"&&<p className="text-caption text-amber-800 dark:text-amber-300">تاریخ انقضای ذکرشده گذشته است؛ اصالت گواهی بررسی نشده است.</p>}
      </div>)}
    </section>)}</div>
    {!!list(data.gaps).length&&<p className="text-caption text-muted">بازه‌هایی بدون سابقهٔ ثبت‌شده وجود دارد؛ رزومه ممکن است ناقص باشد و این به‌تنهایی نکتهٔ منفی نیست.</p>}
    {!!list(data.overlaps).length&&<p className="text-caption text-muted">برخی بازه‌ها هم‌پوشانی دارند؛ ممکن است همکاری هم‌زمان بوده باشد.</p>}
    {Array.isArray(data.warnings)&&data.warnings.includes("employment_section_without_supported_records")&&<p role="status" className="text-caption text-amber-800 dark:text-amber-300">بخش سوابق در متن پیدا شد اما رکورد قابل اتکا از آن ساخته نشد؛ متن اصلی را بررسی کنید.</p>}
  </div>;
}
