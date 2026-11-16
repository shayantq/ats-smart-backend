import {dossierInsights,timelineRows} from './dossierInsights';

test('شکست و ابهام پیش از کمبود داده‌اند؛ نبود شاهد ضعف محسوب نمی‌شود',()=>{
  const parsed={structured:{identity:{name:{value:'Different'}},activities:[]},_extraction:{status:'partial'},_evidence_analysis:{requirements:[{text:'Java',status:'unknown'}]}};
  const d=dossierInsights(parsed,{status:'failed'},'Account');
  expect(d.warnings[0].message).toContain('ناموفق');
  expect(d.unmet).toHaveLength(0);expect(d.unknown).toHaveLength(1);
  expect(d.questions[0]).toContain('Java');
});

test('ترتیب زمانی تقویم استاندارد دارد و مجهول تاریخ‌سازی نمی‌شود',()=>{
  const rows=timelineRows([{id:'unknown',dates:{status:'unknown'}},{id:'old',dates:{status:'valid',start:{earliest:'2020-01-01'},end:{latest:'2021-01-01'}}},{id:'new',dates:{status:'valid',start:{earliest:'2024-01-01'},end:{latest:'2025-01-01'}}}]);
  expect(rows.map(r=>r.id)).toEqual(['new','old','unknown']);
  expect(rows[2].dated).toBe(false);
});
