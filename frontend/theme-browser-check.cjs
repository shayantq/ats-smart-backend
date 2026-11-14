// شواهد اولین رسم با توقف عمدی React؛ داده‌های این بررسی فقط محلی‌اند.
const {chromium}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const out=path.resolve(__dirname,'../training/reports/editorial/darkmode');
async function contrastAudit(page){
 return page.evaluate(()=>{
  const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
  const blend=(a,b)=>a.slice(0,3).map((v,i)=>v*(a[3]??1)+b[i]*(1-(a[3]??1)));
  const lum=c=>c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
  const ratio=(a,b)=>{const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
  const bg=el=>{let chain=[];for(let n=el;n;n=n.parentElement)chain.push(n);let c=[252,252,250];for(const n of chain.reverse())c=blend(rgb(getComputedStyle(n).backgroundColor),c);return c};
  const pairs=new Map();
  for(const el of document.querySelectorAll('body *')){
   if(!el.getClientRects().length||el.closest('[aria-hidden="true"]')||getComputedStyle(el).visibility==='hidden')continue;
   if(el.matches(':disabled,option')||el.closest('svg'))continue;
   const style=getComputedStyle(el),back=bg(el);
   if([...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())){
    const color=style.color,large=parseFloat(style.fontSize)>=24||(parseFloat(style.fontSize)>=18.66&&Number(style.fontWeight)>=700);
    const r=ratio(blend(rgb(color),back),back),key=color+' / '+back.join(',');
    if(!pairs.has(key))pairs.set(key,{kind:'text',color,background:back,ratio:+r.toFixed(2),required:large?3:4.5,example:el.textContent.trim().slice(0,65)});
   }
   if(el.matches('input,select,textarea') && parseFloat(style.borderTopWidth)>0){
    const r=ratio(rgb(style.borderTopColor),back);pairs.set('control'+style.borderTopColor+back.join(),{kind:'control',color:style.borderTopColor,background:back,ratio:+r.toFixed(2),required:3,example:el.tagName});
   }
   if(el===document.activeElement&&style.outlineStyle!=='none'){
    const r=ratio(rgb(style.outlineColor),bg(el.parentElement));pairs.set('focus',{kind:'focus',ratio:+r.toFixed(2),required:3,color:style.outlineColor});
   }
  }
  return [...pairs.values()];
 });
}
module.exports={contrastAudit};
if(require.main===module)(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({channel:'msedge',headless:true});const results=[];
 try {
 for(const os of ['light','dark'])for(const preference of ['light','dark','system']){
  const context=await browser.newContext({colorScheme:os});
  await context.addInitScript(p=>{localStorage.setItem('ats_theme',p)},preference);
  const page=await context.newPage();let release;const held=new Promise(r=>release=r);
  await page.route('**/src/main.tsx',async route=>{await held;await route.continue()});
  await page.goto('http://localhost:5173',{waitUntil:'commit'});
  await page.waitForFunction(()=>document.documentElement.dataset.themePreference);
  const expected=preference==='system'?os:preference;
  const initial=await page.evaluate(()=>({dark:document.documentElement.classList.contains('dark'),background:getComputedStyle(document.documentElement).backgroundColor,react_started:!!document.querySelector('#root')?.children.length}));
  await page.screenshot({path:path.join(out,`first-paint-${preference}-${os}.png`)});
  if(initial.dark!==(expected==='dark')||initial.react_started)throw Error('pre-React theme failed');
  release();await page.getByLabel('حالت نمایش').waitFor();
  await page.reload();await page.getByLabel('حالت نمایش').waitFor();
  if(await page.locator('html').evaluate(el=>el.classList.contains('dark'))!==(expected==='dark'))throw Error('reload theme');
  results.push({os,preference,initial,reload:true});await context.close();
 }
 const context=await browser.newContext();const page=await context.newPage();await page.goto('http://localhost:5173');await page.locator('#login-email').fill('synthetic@example.test');
 const audits=[];
 for(const theme of ['light','dark']){
  await page.getByLabel('حالت نمایش').selectOption(theme);await page.getByLabel('حالت نمایش').focus();
  await page.waitForTimeout(250);
  if(await page.locator('#login-email').inputValue()!=='synthetic@example.test')throw Error('lost form');
  audits.push({theme,pairs:await contrastAudit(page)});await page.screenshot({path:path.join(out,`login-${theme}.png`),fullPage:true});
 }
 await page.getByRole('button',{name:/ثبت‌نام/}).click();await page.screenshot({path:path.join(out,'register-dark.png'),fullPage:true});
 fs.writeFileSync(path.join(out,'bootstrap-checks.json'),JSON.stringify({cases:results,switch_preserves_form:true,contrast:audits},null,2));
 console.log(JSON.stringify({first_paint_cases:results.length,contrast_failures:audits.flatMap(a=>a.pairs.filter(p=>p.ratio<p.required).map(p=>({theme:a.theme,...p})))}));
 await context.close();
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
