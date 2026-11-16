import { dossierData } from "./dossierData";
import type { ApplicationDossier } from "../services/applicationsApi";
const empty:ApplicationDossier={application_id:"a",resume_id:"r",raw_text:null,parsed_data:null,skill_analysis:null,agent_analysis:null};
test("رادار فقط برای سه معیار معتبر عامل موفق و با تبدیل یکسان ۰ تا ۱ به درصد ساخته می‌شود",()=>{
  const items=[{key:"a",label_fa:"همکاری",score:0.2},{key:"b",label_fa:"ارتباط",score:0.7},{key:"c",label_fa:"رهبری",score:1},{key:"x",label_fa:"نامعتبر",score:9}];
  expect(dossierData({...empty,agent_analysis:{soft_skills:{status:"completed",items}}}).radar.map(x=>x.score)).toEqual([20,70,100]);
  expect(dossierData({...empty,agent_analysis:{soft_skills:{status:"failed",items}}}).radar).toEqual([]);
  expect(dossierData({...empty,agent_analysis:{soft_skills:{status:"completed",items:items.slice(0,2)}}}).radar).toEqual([]);
});
test("سوابق با سال استاندارد نزولی مرتب می‌شوند و عنوان یا تاریخ جعلی نمی‌گیرند",()=>{
  const entries=[{company:"قدیمی",start_year_gregorian:2020},{company:"نامعلوم"},{company:"جدید",start_year_gregorian:2024}].map(x=>({...x,source:"resume_evidence_v2",evidence:"شاهد ساختگی"}));
  expect(dossierData({...empty,agent_analysis:{experience:{status:"completed",entries}}}).entries.map(x=>x.company)).toEqual(["جدید","قدیمی","نامعلوم"]);
});

test("سوابق ناموفق و fallback نامستند نمایش داده نمی‌شوند",()=>{
  const data={...empty,agent_analysis:{experience:{status:"failed",entries:[{company:"ساختگی"}]}},skill_analysis:{experience_entries:[{company:"ساختگی"}]},parsed_data:{work_experience:[{company:"مستند",source:"resume_evidence_v2",evidence:"شاهد"}]}};
  expect(dossierData(data).entries.map(x=>x.company)).toEqual(["مستند"]);
});

test("ساختار جدید بر سابقهٔ کش‌شدهٔ قدیمی اولویت دارد و داوطلبی وارد استخدام نمی‌شود",()=>{
  const fact=(value:string)=>({value,status:"extracted",evidence:[{text:value}]});
  const structured={version:"resume-structured-v1",activities:[{kind:"employment",fields:{job_title:fact("Engineer"),company:fact("Maple Labs")},dates:{status:"unknown"}},{kind:"volunteering",fields:{job_title:fact("Volunteer")},dates:{status:"valid"}}]};
  const result=dossierData({...empty,parsed_data:{structured},agent_analysis:{experience:{status:"completed",entries:[{source:"resume_evidence_v2",evidence:"old",company:"Old Cached Company"}]}}});
  expect(result.entries).toHaveLength(1);
  expect(result.entries[0].company).toBe("Maple Labs");
  expect(result.entries[0].is_valid).toBe(false);
});

test('مهارت‌های صریح جدید بر فهرست قدیمی اولویت دارند و استنباط مهارت صریح نمی‌شود',()=>{
  const result=dossierData({...empty,parsed_data:{_evidence_analysis:{version:'evidence-analysis-v2.1',skills:[{name:'FastAPI',basis:'explicit'},{name:'Python',basis:'inferred'}]}},skill_analysis:{skills:['Stale skill']}});
  expect(result.skills).toEqual(['FastAPI']);
});
