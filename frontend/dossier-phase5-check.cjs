// آزمون مرورگر با API و PDF واقعیِ fixture ساختگی؛ فقط فایل‌های همین آزمون ثبت می‌شوند.
const {chromium}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const out=path.resolve(__dirname,'../training/reports/phase5');
const target=JSON.parse(fs.readFileSync(path.join(out,'target.json'),'utf8').replace(/^\uFEFF/,''));
if(target.synthetic!==true)throw Error('synthetic fixture required');

(async()=>{
  const keys=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../secrets/editorial-local.json'),'utf8'));
  const login=await fetch('http://localhost:8000/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'hr@ats-preview.example.com',password:keys.demo})});
  if(!login.ok)throw Error('local fixture login failed');
  const token=(await login.json()).access_token,headers={Authorization:`Bearer ${token}`};
  const base=`http://localhost:8000/api/v1/applications/${target.application_id}`;
  const dossier=await(await fetch(base+'/dossier',{headers})).json();
  const hash=dossier.parsed_data._extraction.file_sha256;
  const document=await fetch(base+'/document/1?expected_sha256='+hash,{headers});
  if(!document.ok||document.headers.get('cache-control')!=='private, no-store')throw Error('live preview failed');
  const meta=await document.json();
  if((await fetch(base+'/document/1')).status!==401)throw Error('anonymous document access');
  if((await fetch(base+'/document/1?expected_sha256='+'0'.repeat(64),{headers})).status!==409)throw Error('version mismatch accepted');
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://localhost:5173');await page.waitForSelector('#root > *');
    await page.evaluate(async({token,id})=>{
      const source=await(await fetch('/src/components/CandidateDossier.tsx')).text();
      const queryPath=source.match(/from ["']([^"']*react-query[^"']*)["']/)[1];
      const [{default:React},{default:DOM},RQ,{default:Dossier}]=await Promise.all([
        import('/node_modules/.vite/deps/react.js'),import('/node_modules/.vite/deps/react-dom_client.js'),import(queryPath),import('/src/components/CandidateDossier.tsx'),
      ]);
      localStorage.setItem('ats_smart_access_token',token);document.getElementById('root').style.display='none';
      const host=document.createElement('div');document.body.append(host);
      DOM.createRoot(host).render(React.createElement(RQ.QueryClientProvider,{client:new RQ.QueryClient()},React.createElement(Dossier,{application:{application_id:id,candidate_name:'نمونهٔ ساختگی — حساب آزمایشی',current_status:'Draft',score_ai:null,updated_at:'2026-11-16T00:00:00Z'},onClose:()=>{window.fixtureClosed=true;}})));
    },{token,id:target.application_id});
    const dialog=page.getByRole('dialog');await dialog.getByText('Harbor Systems',{exact:true}).first().waitFor();
    const history=dialog.getByRole('heading',{name:'سوابق کاری',exact:true}).locator('..');
    await history.getByText('شواهد و وضعیت فیلدهای سابقه',{exact:true}).click();
    await history.getByText('شاهد سمت',{exact:true}).click();
    await history.getByRole('button',{name:'نمایش محل شاهد در سند'}).first().click();
    const highlight=dialog.getByTestId('evidence-highlight');await highlight.waitFor();
    const box=dossier.parsed_data.structured.activities[0].fields.job_title.evidence[0].bbox;
    const drawn=await highlight.boundingBox(),image=await dialog.getByRole('img').boundingBox();
    const expected={x:image.x+box[0]/meta.width*image.width,y:image.y+box[1]/meta.height*image.height};
    if(Math.abs(drawn.x-expected.x)>2||Math.abs(drawn.y-expected.y)>2)throw Error('highlight geometry mismatch');
    await dialog.getByRole('button',{name:'بزرگ‌نمایی سند'}).click();
    const zoomedImage=await dialog.getByRole('img').boundingBox(),zoomedHighlight=await highlight.boundingBox();
    if(Math.abs(zoomedHighlight.width-(box[2]-box[0])/meta.width*zoomedImage.width)>2)throw Error('zoom highlight mismatch');
    await dialog.getByRole('button',{name:'صفحهٔ بعد'}).click();await dialog.getByText('صفحهٔ ۲ از ۲').waitFor();
    if(await highlight.count())throw Error('highlight carried into unrelated page');
    await dialog.getByRole('button',{name:'صفحهٔ قبل'}).click();await highlight.waitFor();
    const results=[];
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>document.documentElement.classList.toggle('dark',theme==='dark'),theme);
      for(const width of [375,768,1440]){
        await page.setViewportSize({width,height:1000});
        const overflow=await dialog.evaluate(el=>({page:document.documentElement.scrollWidth>innerWidth,dialog:el.scrollWidth>el.clientWidth+1}));
        if(overflow.page||overflow.dialog)throw Error('horizontal overflow');
        await dialog.evaluate(el=>{el.scrollTop=0});
        await page.screenshot({path:path.join(out,`synthetic-phase5-${theme}-${width}-overview.png`)});
        await highlight.scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(out,`synthetic-phase5-${theme}-${width}-evidence.png`)});
        results.push({theme,width,overflow});
      }
    }
    await page.getByRole('button',{name:'بستن پرونده'}).focus();
    for(let i=0;i<60;i++){await page.keyboard.press('Tab');if(!await page.evaluate(()=>!!document.activeElement.closest('dialog')))throw Error('focus escaped');}
    await page.emulateMedia({reducedMotion:'reduce'});await page.keyboard.press('Escape');
    if(!await page.evaluate(()=>window.fixtureClosed===true))throw Error('Escape failed');
    if(errors.length)throw Error('browser runtime errors');
    const result={synthetic:true,live_api:true,pdf_render:true,hash_mismatch_rejected:true,anonymous_rejected:true,highlight_geometry:true,zoom_geometry:true,page_navigation:true,focus_trap:true,escape:true,runtime_errors:0,viewports:results};
    fs.writeFileSync(path.join(out,'browser-live.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
