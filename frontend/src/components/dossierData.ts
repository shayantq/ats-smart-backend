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
  const skillNames = array(skills.status === "completed" ? skills.items : data?.skill_analysis?.skills)
    .map(value => typeof value === "string" ? value : text(object(value).name)).filter(Boolean);
  const source = Array.isArray(experience.entries) && experience.entries.length ? experience.entries
    : array(data?.skill_analysis?.experience_entries).length ? data?.skill_analysis?.experience_entries
    : data?.parsed_data?.work_experience;
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
