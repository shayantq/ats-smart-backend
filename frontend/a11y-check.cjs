// ممیزی build واقعی با API ساختگی روی loopback؛ هیچ درخواست یا تغییری در تولید ندارد.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {pathToFileURL}=require('node:url');
const {chromium}=require('@playwright/test');
const {contrastAudit}=require('./theme-browser-check.cjs');
const out=path.resolve(__dirname,process.env.ATS_A11Y_OUTPUT||'../training/reports/a11y');
const root=path.resolve(__dirname,'dist');const url='http://127.0.0.1:4174';
const states=['Draft','Applied','Screening','Technical Interview','HR Interview','Offer','Accepted','Hired','Rejected'];
const pageOf=items=>({items,has_next:false,has_previous:false,next_cursor:null,previous_cursor:null});
const seed=()=>states.map((s,i)=>({application_id:'fixture-'+i,candidate_id:'candidate-'+i,candidate_name:i===2?'مریم احمدی — نمونهٔ ساختگی / Python & React با نام طولانی':'کارجوی ساختگی '+i,current_status:s,score_ai:i===0?null:82,updated_at:'2026-11-15T10:00:00Z'}));
let cards=seed(),fail=false,role='HR_Manager';
const server=http.createServer(async(req,res)=>{
 const params=new URL(req.url,url).searchParams;const p=new URL(req.url,url).pathname;res.setHeader('Cache-Control','no-store');
 if(p.startsWith('/api/v1/')){
  res.setHeader('Content-Type','application/json');let result;
  if(p.endsWith('/auth/me'))result={id:'synthetic-user',email:'user@example.test',role};
  else if(p.endsWith('/candidates/me'))result={candidate_id:'synthetic-candidate',email:'user@example.test',first_name:'مریم',last_name:'نمونهٔ ساختگی',phone:'',skills:['Python']};
  else if(p.endsWith('/candidates/me/offers'))result=pageOf([{application_id:'offer',job_id:'synthetic-job',job_title:'پیشنهاد کاملاً ساختگی',company_name:'شرکت نمونه',updated_at:'2026-11-15T10:00:00Z'}]);
  else if(p.includes('/jobs/'))result=pageOf([{job_id:'synthetic-job',title:'آگهی ساختگی / Python و React',status:'Active'}]);
  else if(p.endsWith('/dossier'))result={application_id:'fixture-2',resume_id:'synthetic-resume',raw_text:('رزومهٔ کاملاً ساختگی برای آزمون خوانایی و دسترس‌پذیری. Python / React\n\n').repeat(25),parsed_data:null,skill_analysis:{skills:['Python','React','همکاری تیمی']},agent_analysis:null};
  else if(p.endsWith('/status')){
   let data='';for await(const chunk of req)data+=chunk;const body=JSON.parse(data);const card=cards.find(c=>c.application_id===p.split('/')[4]);
   if(fail){res.statusCode=500;result={detail:'خطای ساختگی شبکه'};}
   else if(!card||card.current_status!==body.current_status||['Hired','Rejected'].includes(card.current_status)||![states[states.indexOf(card.current_status)+1],'Rejected'].includes(body.new_status)){res.statusCode=400;result={detail:'Business Logic Violation'};}
   else {const previous_status=card.current_status;card.current_status=body.new_status;result={application_id:card.application_id,previous_status,new_status:card.current_status,updated_at:card.updated_at};}
  }
  else if(p.endsWith('/applications/counts'))result=Object.fromEntries(states.map(s=>[s,cards.filter(c=>c.current_status===s).length]));
  else if(p.includes('/applications/')){const list=cards.filter(c=>!params.get('current_status')||c.current_status===params.get('current_status'));const offset=Number(params.get('cursor')||0);const limit=Number(params.get('limit')||50);result={...pageOf(list.slice(offset,offset+limit)),has_next:offset+limit<list.length,next_cursor:offset+limit<list.length?String(offset+limit):null};}
  else if(p.includes('/notifications/'))result={...pageOf([]),unread_count:0};
  else {res.statusCode=404;result={detail:'مسیر دادهٔ ساختگی تعریف نشده است'};}
  res.end(JSON.stringify(result));return;
 }
 const file=path.resolve(root,'.'+(p==='/'?'/index.html':p));
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.statusCode=404;res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.woff2')?'font/woff2':'text/html');
 res.end(fs.readFileSync(file));
});
async function tabTo(page,locator){for(let i=0;i<110;i++){await page.keyboard.press('Tab');if(await locator.count() && await locator.evaluate(el=>el===document.activeElement))return;}throw Error('keyboard target unreachable');}
(async()=>{
 fs.mkdirSync(out,{recursive:true});await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(4174,'127.0.0.1',resolve)});
 const context=await chromium.launchPersistentContext(path.join(out,'browser-profile'),{channel:'msedge',headless:true,args:['--remote-debugging-port=9228']});
 try{
 const checks=[];
 for(const theme of ['light','dark'])for(const width of [375,768,1440]){
  cards=seed();fail=false;const page=await context.newPage();await page.setViewportSize({width,height:1000});
  await page.goto(url);await page.evaluate(t=>{localStorage.setItem('ats_smart_access_token','synthetic-local-fixture');localStorage.setItem('ats_theme',t)},theme);await page.reload();
  await page.getByTestId('kanban-board').waitFor();await page.evaluate(()=>document.fonts.ready);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await tabTo(page,page.locator('#job-select'));await page.keyboard.press('Home');
  const open=page.getByRole('button',{name:/مشاهده پرونده مریم/});await tabTo(page,open);await page.keyboard.press('Enter');
  await page.getByRole('dialog').waitFor();await page.getByText(/رزومهٔ کاملاً ساختگی/).waitFor();
  await page.keyboard.press('Shift+Tab');const trapped=await page.getByRole('dialog').evaluate(el=>el.contains(document.activeElement));
  await page.screenshot({path:path.join(out,`dossier-${theme}-${width}.png`),fullPage:true});
  await page.keyboard.press('Escape');if(!await open.evaluate(el=>el===document.activeElement))throw Error('dialog focus restoration '+theme+' '+width+' '+await page.evaluate(()=>document.activeElement.outerHTML.slice(0,180)));
  const move=page.getByRole('button',{name:/تغییر وضعیت مریم/});await tabTo(page,move);
  await page.keyboard.press('Space');await page.keyboard.press('Escape');
  await page.keyboard.press('Enter');await page.keyboard.press('Enter');
  await page.getByRole('status').filter({hasText:/وضعیت مریم.*با موفقیت به مصاحبه فنی/}).waitFor();
  if(!await move.evaluate(el=>el===document.activeElement))throw Error('move focus');
  fail=true;await page.keyboard.press('Space');await page.keyboard.press('ArrowLeft');await page.keyboard.press('Enter');
  await page.getByRole('status').filter({hasText:/انتقال مریم.*ناموفق بود.*مصاحبه فنی بازگردانده شد/}).waitFor();
  if(!await move.evaluate(el=>el===document.activeElement))throw Error('rollback focus');
  await page.keyboard.press('ArrowLeft');await page.keyboard.press('ArrowRight');
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.waitForTimeout(250);const pairs=await contrastAudit(page);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  await page.screenshot({path:path.join(out,`kanban-${theme}-${width}.png`),fullPage:true});
  checks.push({theme,width,trapped,keyboard_workflow:true,success_and_failure_announcements:true,page_overflow:overflow,errors,contrast:pairs});
  if(!trapped||overflow||errors.length||pairs.some(p=>p.ratio<p.required))throw Error('browser verification failed');await page.close();
 }
 fs.writeFileSync(path.join(out,'browser-checks.json'),JSON.stringify(checks,null,2));
 const actions=[];role='Candidate';
 for(const theme of ['light','dark']){
  const page=await context.newPage();await page.goto(url);await page.evaluate(t=>localStorage.setItem('ats_theme',t),theme);await page.reload();await page.getByRole('tab',{name:'صندوق پیشنهادها'}).waitFor();
  await tabTo(page,page.getByRole('tab',{name:'پروفایل',exact:true}));await page.keyboard.press('End');
  await page.getByRole('button',{name:'قبول پیشنهاد'}).waitFor();
  for(const name of ['قبول پیشنهاد','رد پیشنهاد']){
   const button=page.getByRole('button',{name});
   for(const state of ['normal','hover','focus']){
    if(state==='hover')await button.hover();if(state==='focus'){await page.mouse.move(0,0);await tabTo(page,button);}
    await page.waitForTimeout(250);const pairs=await contrastAudit(page);actions.push({theme,name,state,pairs});if(pairs.some(p=>p.ratio<p.required))throw Error('action contrast');
   }
  }
  await page.screenshot({path:path.join(out,`actions-${theme}.png`),fullPage:true});await page.close();
 }
 fs.writeFileSync(path.join(out,'action-contrast.json'),JSON.stringify(actions,null,2));role='HR_Manager';
 const {default:lighthouse}=await import(pathToFileURL(path.resolve(__dirname,'../training/reports/a11y-tools/node_modules/lighthouse/core/index.js')).href);
 const scores=[];
 for(const theme of ['light','dark']){
  cards=seed();fail=false;const page=await context.newPage();await page.goto(url);await page.evaluate(t=>{localStorage.setItem('ats_smart_access_token','synthetic-local-fixture');localStorage.setItem('ats_theme',t)},theme);await page.reload();await page.getByTestId('kanban-board').waitFor();
  const result=await lighthouse(url,{port:9228,onlyCategories:['accessibility'],output:['html','json'],disableStorageReset:true,logLevel:'error',formFactor:'desktop',screenEmulation:{mobile:false,width:1440,height:1000,deviceScaleFactor:1,disabled:false}});
  fs.writeFileSync(path.join(out,`lighthouse-${theme}.html`),result.report[0]);fs.writeFileSync(path.join(out,`lighthouse-${theme}.json`),result.report[1]);
  const failed=Object.values(result.lhr.audits).filter(a=>a.score===0).map(a=>({id:a.id,title:a.title,details:a.details?.items}));
  scores.push({theme,score:result.lhr.categories.accessibility.score*100,url:result.lhr.finalDisplayedUrl,lighthouse:result.lhr.lighthouseVersion,browser:result.lhr.environment.hostUserAgent,viewport:'1440x1000',fixture:'ساختگی؛ build واقعی، auth و API محلی',failed});await page.close();
 }
 fs.writeFileSync(path.join(out,'lighthouse-summary.json'),JSON.stringify(scores,null,2));console.log(JSON.stringify(scores.map(s=>({...s,failed:s.failed.map(a=>({id:a.id,title:a.title}))}))));
 if(scores.some(s=>s.score<=95))process.exitCode=1;
 }finally{await context.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);server.close();process.exit(1)});
