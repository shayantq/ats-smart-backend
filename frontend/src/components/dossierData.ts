import type { ApplicationDossier } from "../services/applicationsApi";

export function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
const array = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
export const text = (value: unknown): string => typeof value === "string" ? value : "";

/** فقط معیارهای هم‌مقیاس ۰ تا ۱ عامل موفق؛ بدون تبدیل امتیاز کلی به محور ساختگی. */
export function dossierData(data: ApplicationDossier | undefined) {
  const agent = object(data?.agent_analysis);
  const skills = object(agent.skills);
  const experience = object(agent.experience);
  const soft = object(agent.soft_skills);
  const profile=object(data?.parsed_data?._evidence_analysis);
  const skillNames = array(['evidence-analysis-v1','evidence-analysis-v2','evidence-analysis-v2.1'].includes(text(profile.version))?array(profile.skills).map(object).filter(s=>s.basis==='explicit'&&!s.conflict):skills.status === "completed" ? skills.items : data?.skill_analysis?.skills)
    .map(value => typeof value === "string" ? value : text(object(value).name)).filter(Boolean);
  const supported = (value:unknown) => array(value).map(object).filter(entry => ["resume_evidence_v2","resume_evidence_v3"].includes(text(entry.source)) && !!text(entry.evidence));
  const rich=object(data?.parsed_data?.structured);
  const grounded=rich.version==="resume-structured-v1" ? array(rich.activities).map(object).filter(x=>["employment","internship","freelance"].includes(text(x.kind))).map(x=>{
    const fields=object(x.fields), dates=object(x.dates);
    return {job_title:text(object(fields.job_title).value),company:text(object(fields.company).value),duration:text(object(fields.duration).value),
      start_year:object(dates.start).year,start_year_gregorian:Number(text(object(dates.start).earliest).slice(0,4)) || undefined,
      is_valid:dates.status==="valid",fields,claims:x.claims,kind:x.kind,
      flag_reason:dates.status!=="valid"?"تاریخ این سابقه مشخص یا معتبر نیست؛ مدت آن به جمع سابقه افزوده نشده است.":null};
  }) : null;
  const source = grounded ?? (experience.status === "completed" && supported(experience.entries).length ? supported(experience.entries)
    : supported(data?.parsed_data?.work_experience).length ? supported(data?.parsed_data?.work_experience)
    : supported(data?.skill_analysis?.experience_entries));
  const entries: (Record<string, unknown> & {originalIndex:number})[] = array(source).map(object).map((value,index) => ({...value, originalIndex:index}));
  // تقویم‌های بدون معادل استاندارد جدا مرتب می‌شوند؛ تبدیل تقریبی تاریخ انجام نمی‌دهیم.
  entries.sort((a,b) => {
    const date = (v: Record<string, unknown>): [number,number] => typeof v.start_year_gregorian === "number" ? [0,v.start_year_gregorian]
      : typeof v.start_year === "number" ? [v.start_year < 1700 ? 1 : 0,v.start_year] : [2,0];
    const [aGroup,aYear]=date(a);const [bGroup,bYear]=date(b);
    return aGroup-bGroup || bYear-aYear || a.originalIndex-b.originalIndex;
  });
  const seen = new Set<string>();
  const radar = (soft.status === "completed" ? array(soft.items) : []).map(object).filter(v => {
    if(!text(v.key) || !text(v.label_fa) || typeof v.score !== "number" || !Number.isFinite(v.score) || v.score < 0 || v.score > 1 || seen.has(text(v.key))) return false;
    seen.add(text(v.key));return true;
  }).map(v => ({label:text(v.label_fa), score:(v.score as number)*100}));
  return {skills:[...new Set(skillNames)],entries,radar:radar.length >= 3 ? radar : []};
}
