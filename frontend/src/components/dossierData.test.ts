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
  const entries=[{company:"قدیمی",start_year_gregorian:2020},{company:"نامعلوم"},{company:"جدید",start_year_gregorian:2024}];
  expect(dossierData({...empty,agent_analysis:{experience:{entries}}}).entries.map(x=>x.company)).toEqual(["جدید","قدیمی","نامعلوم"]);
});
