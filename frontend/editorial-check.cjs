// بررسی بصری محلی با داده‌های کاملاً ساختگی؛ هیچ درخواست API به سرور ارسال نمی‌شود.
const { chromium } = require('@playwright/test');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const path = require('node:path');
const theme = process.env.ATS_TEST_THEME || 'light';
const out = path.resolve(__dirname, '../training/reports/editorial', process.env.ATS_TEST_THEME ? `darkmode/${theme}` : '');
const phase = process.argv[2] || 'after';
const contrast=[];
const {contrastAudit}=require('./theme-browser-check.cjs');
async function audit(page){if(process.env.ATS_TEST_THEME){await page.waitForTimeout(250);contrast.push(...await contrastAudit(page));}}

const server = process.env.ATS_EXISTING_SERVER ? {kill(){}} : spawn(process.execPath, [path.join(__dirname, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5173', '--strictPort'], {cwd:__dirname,stdio:'ignore'});
const states = ['Draft','Applied','Screening','Technical Interview','HR Interview','Offer','Accepted','Hired','Rejected'];
const pageOf = items => ({items, has_next:false, has_previous:false, next_cursor:null, previous_cursor:null});
const applications = states.flatMap((s,i)=>Array.from({length:i<3?3:1},(_,j)=>({application_id:`app-${i}-${j}`,candidate_id:`person-${i}-${j}`,candidate_name: j===1?'مریم احمدی؛ پژوهشگر تجربهٔ کاربر و توسعه‌دهندهٔ Python / React':'کارجوی آزمایشی '+(i+1)+' ـ '+(j+1),current_status:s,score_ai:j===2?null:82-i*5,updated_at:'2026-11-10T10:00:00Z'})));
(async()=>{
 for(let i=0;i<60;i++){try{if((await fetch('http://127.0.0.1:5173')).ok)break;}catch{}await new Promise(r=>setTimeout(r,250));}
 fs.mkdirSync(out,{recursive:true});
 const browser = await chromium.launch({channel:'msedge',headless:true});
 const results=[];
 for(const width of [375,768,1440]){
  const context=await browser.newContext({viewport:{width,height:1000},locale:'fa-IR'});
  await context.addInitScript(()=>localStorage.setItem('ats_smart_access_token','synthetic-visual-fixture'));
  await context.addInitScript(value=>localStorage.setItem('ats_theme',value),theme);
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let empty=false;let populatedAnalytics=false;let dialogChecks=null;let typographyChecks=null;
  await page.route('**/api/v1/**',async route=>{
   const u=new URL(route.request().url());let body;
   if(u.pathname.endsWith('/auth/me'))body={user_id:'fixture-hr',email:'hr@example.test',role:'HR_Manager'};
   else if(u.pathname.includes('/auth/sessions/'))body={items:[]};
   else if(u.pathname.includes('/interviews/'))body=pageOf([]);
   else if(u.pathname.includes('/jobs/'))body=pageOf([{job_id:'fixture-job',title:'توسعه‌دهندهٔ محصول / Python و React — دادهٔ ساختگی',department:'محصول',description:'آگهی آزمایشی',skills_required:['Python','React'],status:'Active',created_by:'fixture-hr',created_at:null}]);
   else if(u.pathname.endsWith('/dossier'))body={application_id:u.pathname.split('/')[4],resume_id:'fixture-resume',raw_text:('این رزومه و تمام داده‌های این صفحه ساختگی‌اند. توسعهٔ سرویس‌های Python / React با تمرکز بر دسترس‌پذیری و امنیت.\n\n').repeat(18),parsed_data:null,skill_analysis:{skills:['Python','React','طراحی تجربهٔ کاربر']},agent_analysis:{skills:{status:'completed',items:[{name:'Python'},{name:'React'},{name:'طراحی تجربهٔ کاربر'}]},experience:{entries:[{company:'شرکت دادهٔ نمونه',job_title:'توسعه‌دهندهٔ ارشد',duration:'۲۰۲۲ تا ۲۰۲۵',start_year_gregorian:2022,is_valid:true},{company:'شرکت قدیمی نمونه',job_title:'توسعه‌دهنده',duration:'۲۰۱۹ تا ۲۰۲۲',start_year_gregorian:2019,is_valid:true}]},soft_skills:{status:'completed',items:[{key:'communication',label_fa:'ارتباط',score:0.6},{key:'teamwork',label_fa:'همکاری',score:0.8},{key:'leadership',label_fa:'رهبری',score:0.4}]}}};
   else if(u.pathname.includes('/applications/'))body=pageOf(empty?[]:applications);
   else if(u.pathname.includes('/notifications/'))body={...pageOf([]),unread_count:0};
   else if(u.pathname.includes('funnel'))body={stages:populatedAnalytics?states.slice(1,8).map((stage,i)=>({stage,count:28-i*4})):[]};
   else if(u.pathname.includes('trend'))body={series:populatedAnalytics?Array.from({length:7},(_,i)=>({date:`2026-11-${String(i+1).padStart(2,'0')}`,count:i+2})):[]};
   else return route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({detail:'fixture endpoint not provided'})});
   return route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto('http://127.0.0.1:5173');await page.getByTestId('kanban-board').waitFor();await page.evaluate(()=>document.fonts.ready);await audit(page);await page.screenshot({path:path.join(out,`${phase}-kanban-${width}.png`),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  if(phase==='after'){
   await page.getByRole('button',{name:/مشاهده پرونده/}).first().click();
   await page.getByRole('dialog').waitFor();await page.getByText('شرکت دادهٔ نمونه',{exact:true}).waitFor();await page.getByText('سیگنال‌های مهارت نرم؛',{exact:false}).waitFor();await page.waitForTimeout(250);await audit(page);await page.screenshot({path:path.join(out,`${phase}-profile-${width}.png`),fullPage:true});
   const focusInside=await page.getByRole('dialog').evaluate(el=>el.contains(document.activeElement));
   await page.keyboard.press('Shift+Tab');const trapped=await page.getByRole('dialog').evaluate(el=>el.contains(document.activeElement));
   await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'});
   const restored=await page.getByRole('button',{name:/مشاهده پرونده/}).first().evaluate(el=>el===document.activeElement);
   if(!focusInside||!trapped||!restored)throw Error('dialog keyboard behavior failed');
   dialogChecks={focus_inside:focusInside,tab_trapped:trapped,focus_restored:restored,escape_closed:true};
   await page.getByRole('button',{name:/مشاهده پرونده/}).first().click();
   const typography=await page.getByRole('dialog').evaluate(el=>{
    const section=document.createElement('section');section.className='editorial-panel';section.innerHTML='<h3>نمونهٔ آزمون تایپوگرافی؛ دادهٔ ساختگی خارج از API</h3>';
    const p=document.createElement('p');p.className='reading-copy';p.textContent=('این متن ساختگی برای بررسی خوانایی و شکستن خط در نمایش رزومه است. Python / React و طراحی رابط فارسی.\n\n').repeat(12)+'https://example.test/'+ 'long-reference-'.repeat(20);section.append(p);el.firstElementChild.append(section);el.scrollTop=el.scrollHeight;
    return {line_height:getComputedStyle(p).lineHeight,font_size:getComputedStyle(p).fontSize,overflow:el.scrollWidth>el.clientWidth};
   });
   await page.waitForTimeout(250);await audit(page);await page.screenshot({path:path.join(out,`${phase}-typography-${width}.png`),fullPage:true});
   if(typography.overflow)throw Error('long text overflow');
   typographyChecks=typography;
   await page.keyboard.press('Escape');
  }
  await page.getByRole('tab',{name:'داشبورد تحلیلی'}).click();await audit(page);await page.screenshot({path:path.join(out,`${phase}-dashboard-${width}.png`),fullPage:true});
  if(phase==='after'){
   populatedAnalytics=true;await page.reload();await page.getByRole('tab',{name:'داشبورد تحلیلی'}).click();await page.locator('.recharts-wrapper').first().waitFor();await page.waitForTimeout(1800);await audit(page);await page.screenshot({path:path.join(out,`${phase}-dashboard-populated-${width}.png`),fullPage:true});
  }
  if(process.env.ATS_TEST_THEME){
   await page.getByRole('tab',{name:'ثبت آگهی',exact:true}).click();await audit(page);await page.screenshot({path:path.join(out,`job-form-${width}.png`),fullPage:true});
   await page.getByRole('tab',{name:'اعلان‌های فنی'}).click();await audit(page);await page.screenshot({path:path.join(out,`notifications-${width}.png`),fullPage:true});
   await page.getByRole('tab',{name:'مصاحبه‌های امروز'}).click();await audit(page);await page.screenshot({path:path.join(out,`interviews-empty-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'نشست‌های فعال',exact:true}).click();await audit(page);await page.screenshot({path:path.join(out,`sessions-empty-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'بازگشت',exact:true}).click();
  }
  await page.getByRole('tab',{name:'بورد کانبان'}).click();empty=true;await page.reload();await page.getByText('کارتی در این مرحله نیست').first().waitFor();await audit(page);await page.screenshot({path:path.join(out,`${phase}-empty-${width}.png`),fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});
  const duration=await page.getByRole('tab').first().evaluate(el=>getComputedStyle(el).transitionDuration);
  if(phase==='after'){
   await page.getByRole('tab',{name:'بورد کانبان'}).focus();await page.keyboard.press('End');
   if(await page.getByRole('tab',{name:'اعلان‌های فنی'}).getAttribute('aria-selected')!=='true')throw Error('tab End failed');
   await page.keyboard.press('Home');await page.keyboard.press('ArrowLeft');
   if(await page.getByRole('tab',{name:'ثبت آگهی',exact:true}).getAttribute('aria-selected')!=='true')throw Error('RTL tab navigation failed');
  }
  const fontLoaded=await page.evaluate(()=>document.fonts.check('16px Vazirmatn'));
  results.push({width,page_overflow:overflow,errors,reduced_motion_duration:duration,dialog:dialogChecks,typography:typographyChecks,font_loaded:fontLoaded});
  if(errors.length|| (phase==='after'&&overflow))throw Error(JSON.stringify(results));
  await context.close();
 }
 fs.writeFileSync(path.join(out,'contrast.json'),JSON.stringify(contrast,null,2));await browser.close();server.kill();fs.writeFileSync(path.join(out,phase+'-checks.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
})().catch(e=>{server.kill();console.error(e);process.exit(1)});
