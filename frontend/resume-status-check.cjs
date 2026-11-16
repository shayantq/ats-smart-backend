// بررسی نمایش وضعیت‌ها روی Vite محلی؛ همهٔ داده‌ها ساختگی‌اند.
const {chromium} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const out = path.resolve(__dirname, '../training/reports/resume-repair');
fs.mkdirSync(out, {recursive:true});
(async()=>{
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error=>errors.push(error.message));
    await page.goto('http://localhost:5173');
    await page.waitForSelector('#root > *');
    await page.evaluate(async()=>{
      const [{default:React}, {default:ReactDOM}, {default:Status}] = await Promise.all([
        import('/node_modules/.vite/deps/react.js'), import('/node_modules/.vite/deps/react-dom_client.js'),
        import('/src/components/ResumeProcessingStatus.tsx'),
      ]);
      document.getElementById('root').style.display='none';
      const container = document.createElement('main');
      container.dir='rtl';
      container.className='mx-auto max-w-3xl p-6 text-ink bg-paper';
      container.id='synthetic-status-fixture';
      document.body.append(container);
      ReactDOM.createRoot(container).render(React.createElement(React.Fragment,null,
        React.createElement('h1',{className:'text-heading'},'نمونهٔ ساختگی — وضعیت پردازش رزومه'),
        ...['queued','processing','retrying','succeeded','failed'].map(status=>React.createElement('section',
          {key:status,className:'editorial-panel'},React.createElement(Status,{state:{status,stage:'inference',attempt:1,
            error_code: status==='failed' ? 'context_limit_exceeded' : status==='retrying' ? 'engine_unavailable' : null}}))),
      ));
    });
    await page.getByRole('alert').waitFor();
    if (!(await page.getByRole('alert').innerText()).includes('تحلیل ناموفق بود')) throw Error('failure presentation missing');
    const results = [];
    for (const width of [375,1440]) {
      await page.setViewportSize({width,height:900});
      const overflow = await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
      if (overflow) throw Error('horizontal overflow');
      await page.screenshot({path:path.join(out,`synthetic-status-${width}.png`),fullPage:true});
      results.push({width,overflow,statusMessages:await page.getByRole('status').count(),alerts:await page.getByRole('alert').count()});
    }
    if(errors.length) throw Error(errors.join('\n'));
    fs.writeFileSync(path.join(out,'rendered-status-check.json'),JSON.stringify(results,null,2));
    console.log(JSON.stringify(results));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
