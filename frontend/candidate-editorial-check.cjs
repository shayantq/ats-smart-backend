// بررسی رابط با داده‌های ساختگی؛ هیچ درخواست API به سرور ارسال نمی‌شود.
const { chromium } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const out = path.resolve(__dirname, '../training/reports/editorial');
const phase = process.argv[2] || 'after';
const pageOf = items => ({items,has_next:false,has_previous:false,next_cursor:null,previous_cursor:null});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
 const results=[];
 for(const width of [375,768,1440]){
  const context=await browser.newContext({viewport:{width,height:1000},locale:'fa-IR'});
  await context.addInitScript(()=>localStorage.setItem('ats_smart_access_token','synthetic-fixture'));
  const page=await context.newPage();const errors=[];let empty=false;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/v1/**',route=>{
   const u=new URL(route.request().url());let body;
   if(u.pathname.endsWith('/auth/me'))body={user_id:'fixture',role:'Candidate',email:'candidate@example.test'};
   else if(u.pathname.endsWith('/candidates/me'))body={candidate_id:'fixture',email:'candidate@example.test',first_name:'مریم',last_name:'احمدی — دادهٔ ساختگی',phone:'09120000000',skills:['Python','React / TypeScript','طراحی تجربهٔ کاربر','VeryLongSkillNameWithoutSpaces'.repeat(5)]};
   else if(u.pathname.endsWith('/candidates/me/applications'))body=pageOf(empty?[]:['Screening','Rejected','Offer'].map((s,i)=>({application_id:String(i),job_id:'job',job_title:'توسعه‌دهندهٔ محصول و تجربهٔ کاربر / Python & React — نمونهٔ ساختگی با عنوان طولانی برای بررسی خوانایی',current_status:s,updated_at:'2026-11-14T10:00:00Z'})));
   else if(u.pathname.endsWith('/candidates/me/offers'))body=pageOf(empty?[]:[{application_id:'offer',job_id:'job',job_title:'توسعه‌دهندهٔ ارشد Python / React — دادهٔ ساختگی',company_name:'شرکت نمونهٔ آزمایشی با نام بلند برای بررسی نمایش در موبایل',updated_at:'2026-11-14T10:00:00Z'}]);
   else if(u.pathname.includes('/jobs/'))body=pageOf([{job_id:'job',title:'توسعه‌دهندهٔ محصول — دادهٔ ساختگی',status:'Active'}]);
   else if(u.pathname.includes('/notifications/'))body={...pageOf([]),unread_count:0};
   else return route.fulfill({status:404,json:{detail:'fixture endpoint unavailable'}});
   return route.fulfill({json:body});
  });
  await page.goto('http://localhost:5173');await page.getByRole('tab').first().waitFor();await page.locator('input[value="مریم"]').waitFor();await page.evaluate(()=>document.fonts.ready);
  const checks=[];
  for(let i=0;i<3;i++){
   await page.getByRole('tab').nth(i).click();
   if(i===1)await page.getByText(/آخرین به‌روزرسانی/).first().waitFor();
   if(i===2)await page.getByRole('button',{name:'قبول پیشنهاد'}).waitFor();
   await page.screenshot({path:path.join(out,`candidate-${phase}-${['profile','tracker','offers'][i]}-${width}.png`),fullPage:true});
   checks.push(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  empty=true;await page.reload();
  for(let i=1;i<3;i++){await page.getByRole('tab').nth(i).click();await page.getByText(i===1?'هنوز برای هیچ آگهی‌ای درخواست نداده‌ای.':'فعلاً هیچ پیشنهاد شغلی فعالی نداری.').waitFor();await page.screenshot({path:path.join(out,`candidate-${phase}-empty-${i}-${width}.png`),fullPage:true});}
  if(phase==='after'){
   await page.getByRole('tab').first().focus();await page.keyboard.press('End');
   if(await page.getByRole('tab').nth(2).getAttribute('aria-selected')!=='true')throw Error('End navigation');
   await page.keyboard.press('Home');await page.keyboard.press('ArrowLeft');
   if(await page.getByRole('tab').nth(1).getAttribute('aria-selected')!=='true')throw Error('RTL navigation');
   await page.emulateMedia({reducedMotion:'reduce'});
   if(await page.getByRole('tab').first().evaluate(el=>parseFloat(getComputedStyle(el).transitionDuration))!==0)throw Error('reduced motion');
  }
  results.push({width,no_page_overflow:checks.every(Boolean),errors});
  if(phase==='after'&&(!checks.every(Boolean)||errors.length))throw Error(JSON.stringify(results));
  await context.close();
 }
 fs.writeFileSync(path.join(out,`candidate-${phase}-checks.json`),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
