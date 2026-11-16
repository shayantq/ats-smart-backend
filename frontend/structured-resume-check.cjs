// بررسی مرورگر با پروندهٔ کاملاً ساختگی؛ دادهٔ کاربر و سرور خوانده نمی‌شود.
const {chromium}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const out=process.env.ATS_EVIDENCE_REPORT_DIR?path.resolve(process.env.ATS_EVIDENCE_REPORT_DIR):path.resolve(__dirname,'../training/reports/phase3');
const fixture=JSON.parse(fs.readFileSync(path.join(out,'synthetic-dossier.json'),'utf8'));

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const errors=[];
  const results=[];
  try {
    const page=await browser.newPage();
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/v1/applications/synthetic-phase3/dossier',route=>route.fulfill({json:fixture}));
    await page.goto('http://localhost:5173');
    await page.waitForSelector('#root > *');
    await page.evaluate(async()=>{
      const source=await(await fetch('/src/components/CandidateDossier.tsx')).text();
      const queryPath=source.match(/from ["']([^"']*react-query[^"']*)["']/)[1];
      const [{default:React},{default:DOM},RQ,{default:Dossier}]=await Promise.all([
        import('/node_modules/.vite/deps/react.js'),import('/node_modules/.vite/deps/react-dom_client.js'),
        import(queryPath),import('/src/components/CandidateDossier.tsx'),
      ]);
      localStorage.setItem('ats_smart_access_token','synthetic-browser-only');
      document.getElementById('root').style.display='none';
      const container=document.createElement('div');document.body.append(container);
      DOM.createRoot(container).render(React.createElement(RQ.QueryClientProvider,{client:new RQ.QueryClient()},
        React.createElement(Dossier,{application:{application_id:'synthetic-phase3',candidate_name:'نمونهٔ ساختگی — حساب آزمایشی',
          current_status:'Draft',score_ai:null,updated_at:'2026-11-16T00:00:00Z'},onClose:()=>{window.fixtureClosed=true;}})));
    });
    const dialog=page.getByRole('dialog');
    await dialog.getByText('اطلاعات مستند رزومه',{exact:true}).waitFor();
    if(await dialog.locator('ol > li > p').filter({hasText:/^Harbor Systems$/}).count()!==1)throw Error('work record missing or duplicated');
    await page.getByRole('button',{name:'بستن پرونده'}).focus();
    await page.keyboard.press('Tab');
    const firstTab=await page.evaluate(()=>document.activeElement.tagName);
    if(firstTab!=='SUMMARY')throw Error('evidence cannot be reached with Tab');
    await page.keyboard.press('Enter');
    if(!await page.evaluate(()=>document.activeElement.parentElement.open))throw Error('keyboard evidence expansion failed');
    for(let i=0;i<50;i++){
      await page.keyboard.press('Tab');
      if(!await page.evaluate(()=>document.activeElement.closest('dialog')!==null))throw Error('focus escaped modal');
    }
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>document.documentElement.classList.toggle('dark',theme==='dark'),theme);
      for(const width of [375,768,1440]){
        await page.setViewportSize({width,height:900});
        const metrics=await dialog.evaluate(el=>({pageOverflow:document.documentElement.scrollWidth>innerWidth,
          dialogOverflow:el.scrollWidth>el.clientWidth+1,dialogScroll:el.scrollHeight>el.clientHeight}));
        if(metrics.pageOverflow||metrics.dialogOverflow)throw Error('horizontal overflow '+width);
        await dialog.evaluate(el=>{el.scrollTop=0;});
        await page.screenshot({path:path.join(out,`synthetic-dossier-${theme}-${width}-top.png`)});
        await dialog.getByText('اطلاعات مستند رزومه',{exact:true}).scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(out,`synthetic-dossier-${theme}-${width}-facts.png`)});
        const analysis=dialog.getByRole('heading',{name:'تحلیل مستند مهارت و شرایط آگهی',exact:true});
        if(await analysis.count()){
          await analysis.scrollIntoViewIfNeeded();
          await page.screenshot({path:path.join(out,`synthetic-dossier-${theme}-${width}-analysis.png`)});
        }
        results.push({theme,width,...metrics});
      }
    }
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.keyboard.press('Escape');
    if(!await page.evaluate(()=>window.fixtureClosed===true))throw Error('Escape failed');
    if(errors.length)throw Error('browser runtime errors');
    const report={synthetic:true,api:'intercepted_synthetic_fixture',real_model:false,keyboard_evidence:true,focus_trapped:true,
      escape:true,reduced_motion:true,errors:errors.length,viewports:results};
    fs.writeFileSync(path.join(out,'browser-check.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
