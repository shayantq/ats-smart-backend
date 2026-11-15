// ممیزی build واقعی با API ساختگی روی loopback؛ هیچ درخواست یا تغییری در تولید ندارد.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {pathToFileURL}=require('node:url');
const {chromium}=require('@playwright/test');
const {contrastAudit}=require('./theme-browser-check.cjs');
const out=path.resolve(__dirname,'../training/reports/virtual');
const root=path.resolve(__dirname,'dist');const url='http://127.0.0.1:4174';
const states=['Draft','Applied','Screening','Technical Interview','HR Interview','Offer','Accepted','Hired','Rejected'];
const pageOf=items=>({items,has_next:false,has_previous:false,next_cursor:null,previous_cursor:null});
const seed=()=>Array.from({length:10000},(_,i)=>({application_id:'fixture-'+i,candidate_id:'c-'+i,candidate_name:'Synthetic applicant '+i+' / Python React',current_status:i<9900?'Draft':states[1+i%8],score_ai:82,updated_at:'2026-11-15T10:00:00Z'}));
let cards=seed(),fail=false,role='HR_Manager',stress=false;
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
  else if(p.includes('/applications/')){const list=cards.filter(c=>!params.get('current_status')||c.current_status===params.get('current_status'));const offset=Number(params.get('cursor')||0);const limit=stress?10000:Number(params.get('limit')||50);result={...pageOf(list.slice(offset,offset+limit)),has_next:offset+limit<list.length,next_cursor:offset+limit<list.length?String(offset+limit):null};}
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
 fs.mkdirSync(out,{recursive:true});await new Promise(r=>server.listen(4174,'127.0.0.1',r));
 const browser=await chromium.launch({channel:'msedge',headless:true});const results=[];
 try{
 for(const mode of ['paged','stress']){
  stress=mode==='stress';
  for(let run=0;run<5;run++){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(()=>localStorage.setItem('ats_smart_access_token','synthetic-local-fixture'));
   const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
   const start=performance.now();await page.goto(url);await page.locator('[data-move-id="fixture-0"]').waitFor();
   await page.locator('[data-move-id="fixture-0"]').focus();await page.keyboard.press('Enter');await page.getByRole('status').filter({hasText:/مقصد/}).waitFor();const interactive=performance.now()-start;await page.keyboard.press('Escape');
   const initial=await page.evaluate(()=>({cards:document.querySelectorAll('[data-testid="application-card"]').length,nodes:document.querySelectorAll('*').length,heap:performance.memory?.usedJSHeapSize}));
   if(run===0){
    const session=await context.newCDPSession(page);await session.send('Tracing.start',{categories:'devtools.timeline,disabled-by-default-devtools.timeline,blink.user_timing',transferMode:'ReturnAsStream'});
    const viewport=page.locator('[data-virtual-viewport="Draft"]');await viewport.hover();
    for(let i=0;i<30;i++){await page.mouse.wheel(0,500);await page.waitForTimeout(20);}
    await page.waitForTimeout(250);
    const complete=new Promise(resolve=>session.once('Tracing.tracingComplete',resolve));await session.send('Tracing.end');const event=await complete;let trace='';
    for(;;){const chunk=await session.send('IO.read',{handle:event.stream});trace+=chunk.data;if(chunk.eof)break;}await session.send('IO.close',{handle:event.stream});fs.writeFileSync(path.join(out,`trace-${mode}.json`),trace);
    const parsed=JSON.parse(trace).traceEvents;const frames=parsed.filter(e=>e.name==='AnimationFrame::Presentation').map(e=>e.ts).sort((a,b)=>a-b);const intervals=frames.slice(1).map((t,i)=>(t-frames[i])/1000).sort((a,b)=>a-b);
    const metrics={frame_intervals:intervals.length,p95_frame_ms:intervals[Math.floor(intervals.length*.95)],intervals_over_16_7:intervals.filter(x=>x>16.7).length,intervals_over_33_4:intervals.filter(x=>x>33.4).length,long_tasks:parsed.filter(e=>e.name==='RunTask'&&e.dur>50000).length};
    fs.writeFileSync(path.join(out,`scroll-${mode}.json`),JSON.stringify(metrics,null,2));
    await page.screenshot({path:path.join(out,`${mode}-1440.png`),fullPage:true});
    if(mode==='stress'){
      await viewport.evaluate(el=>{el.scrollTop=el.scrollHeight});await page.waitForTimeout(200);
      await viewport.evaluate(el=>{el.scrollTop=el.scrollHeight});
      await page.locator('[data-move-id="fixture-9899"]').waitFor();
      await page.screenshot({path:path.join(out,'stress-last-record.png'),fullPage:true});
    }
   }
   const after=await page.locator('[data-testid="application-card"]').count();
   results.push({mode,run,interactive_ms:interactive,initial,mounted_after_scroll:after,heap_after:await page.evaluate(()=>performance.memory?.usedJSHeapSize),errors});
   if(initial.cards>40||after>40||errors.length)throw Error('DOM bound or runtime failure');await context.close();
  }
 }
 const interaction=[];stress=false;
 for(const theme of ['light','dark'])for(const width of [375,768,1440]){
  const context=await browser.newContext({viewport:{width,height:1000}});const page=await context.newPage();
  await context.addInitScript(t=>{localStorage.setItem('ats_smart_access_token','synthetic-local-fixture');localStorage.setItem('ats_theme',t)},theme);
  await page.goto(url);await page.locator('[data-move-id="fixture-0"]').waitFor();await page.locator('[data-move-id="fixture-0"]').focus();
  for(let i=0;i<55;i++){await page.keyboard.press('ArrowDown');await page.waitForTimeout(10);}
  await page.waitForFunction(()=>document.activeElement?.getAttribute('data-move-id')==='fixture-55');
  const card=page.getByTestId('application-card').filter({hasText:'Synthetic applicant 55 /'});await card.getByRole('button',{name:/مشاهده پرونده/}).click();
  await page.getByRole('dialog').waitFor();await page.locator('[data-virtual-viewport="Draft"]').evaluate(el=>{el.scrollTop=0});await page.waitForTimeout(150);
  if(!await page.getByRole('dialog').isVisible())throw Error('virtualized dossier lost');await page.keyboard.press('Escape');
  await page.waitForTimeout(150);const mounted=await page.getByTestId('application-card').count();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow||mounted>40)throw Error('responsive DOM bound');
  await page.screenshot({path:path.join(out,`keyboard-${theme}-${width}.png`),fullPage:true});interaction.push({theme,width,keyboard_across_page:true,dossier_survives_scroll:true,mounted,overflow});await context.close();
 }
 fs.writeFileSync(path.join(out,'interaction.json'),JSON.stringify(interaction,null,2));
 fs.writeFileSync(path.join(out,'performance.json'),JSON.stringify({browser:browser.version(),hardware:require('node:os').cpus()[0].model,ram_gib:require('node:os').totalmem()/1024**3,viewport:'1440x1000',cpu_throttling:'none',network:'loopback; no throttle',cache:'fresh context per run',dataset:10000,results},null,2));console.log(JSON.stringify(results));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exit(1)});
