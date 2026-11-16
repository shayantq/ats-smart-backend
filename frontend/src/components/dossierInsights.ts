import {object,text} from './dossierData';
export const records=(value:unknown):Record<string,unknown>[]=>Array.isArray(value)?value.map(object):[];

export function dossierInsights(parsed:unknown,processing:unknown,accountName:string) {
  const data=object(parsed),s=object(data.structured),analysis=object(data._evidence_analysis),state=object(processing);
  const activities=records(s.activities),skills=records(analysis.skills),requirements=records(analysis.requirements);
  const name=object(object(s.identity).name);
  const warnings:{priority:number;message:string}[]=[];
  if(state.status==='failed')warnings.push({priority:0,message:'تحلیل ناموفق است؛ فقط داده‌های حفظ‌شده را بررسی کنید.'});
  if(object(data._extraction).status==='partial')warnings.push({priority:1,message:'استخراج ناقص است؛ بعضی بخش‌های فایل ممکن است خوانده نشده باشند.'});
  if(text(name.value)&&text(name.value).trim().toLowerCase()!==accountName.trim().toLowerCase())warnings.push({priority:2,message:'نام فایل و نام حساب متفاوت‌اند؛ هویت را پیش از تصمیم‌گیری تطبیق دهید.'});
  if(name.status==='ambiguous')warnings.push({priority:2,message:'هویت داخل فایل مبهم است؛ چند نام محتمل وجود دارد.'});
  if(requirements.some(r=>r.reason==='conflicting_job_requirements'))warnings.push({priority:2,message:'شرایط آگهی با هم تعارض دارند و باید اصلاح شوند.'});
  if(activities.some(a=>object(a.dates).status!=='valid'))warnings.push({priority:3,message:'بعضی فعالیت‌ها تاریخ معتبر ندارند؛ جمع سابقه شامل مدت مجهول نیست.'});
  if(skills.some(s=>s.conflict))warnings.push({priority:3,message:'برای برخی مهارت‌ها شواهد متناقض دیده شده است.'});
  const met=requirements.filter(r=>r.status==='met'),unmet=requirements.filter(r=>r.status==='unmet'),unknown=requirements.filter(r=>r.status==='unknown');
  const sections=[['هویت فایل',!!text(name.value)],['تماس',!!records(s.contacts).length],['فعالیت‌ها',!!activities.length],['تحصیلات',!!records(s.education).length],['مهارت مستند',!!skills.length],['شروط آگهی',!!requirements.length]] as const;
  const questions=unknown.slice(0,5).map(r=>`برای شرط «${text(r.text)}» چه نمونهٔ مشخص و قابل بررسی از تجربه یا مدرک خود دارید؟`);
  for(const p of records(analysis.projects).slice(0,3))questions.push(`در پروژهٔ «${text(object(p.title).value)||'بدون عنوان'}» سهم شخصی شما، نقش تیم و فناوری‌های استفاده‌شده چه بود؟`);
  for(const a of records(analysis.achievements).slice(0,3))questions.push(`عدد ذکرشده در «${text(object(a.claim).value)}» چگونه اندازه‌گیری شد و سهم شما در نتیجه چه بود؟`);
  return {warnings:warnings.sort((a,b)=>a.priority-b.priority),sections,met,unmet,unknown,questions,activities,skills,requirements,structured:s,analysis};
}

export function timelineRows(activities:Record<string,unknown>[]):(Record<string,unknown>&{index:number;start:string;end:string;dated:boolean})[] {
  return activities.map((a,index)=>{
    const dates=object(a.dates),start=text(object(dates.start).earliest),end=text(object(dates.end).latest);
    return {...a,index,start,end,dated:dates.status==='valid'&&!!start&&!!end};
  }).sort((a,b)=>Number(b.dated)-Number(a.dated)||b.start.localeCompare(a.start)||a.index-b.index);
}
