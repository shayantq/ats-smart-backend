// بررسی واقعی فقط با پروندهٔ ساختگی اختصاصی و API محلی؛ بدون چاپ توکن یا متن رزومه.
const { chromium } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const out = path.resolve(__dirname, process.env.ATS_DOSSIER_OUTPUT || '../training/reports/phase6');
const prefix = process.env.ATS_DOSSIER_PREFIX || 'phase6';
const target = JSON.parse(fs.readFileSync(path.join(out, 'target.json'), 'utf8'));
if (target.synthetic !== true) throw Error('synthetic fixture required');

(async () => {
  const keys = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../secrets/editorial-local.json'), 'utf8'));
  const origin = 'http://localhost:8000/api/v1';
  const login = await fetch(origin + '/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'hr@ats-preview.example.com', password: keys.demo }) });
  if (!login.ok) throw Error('local fixture login failed');
  const token = (await login.json()).access_token;
  async function api(route, body) {
    const response = await fetch(origin + route, { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw Error(`local fixture API failed ${response.status}`);
    return response.json();
  }
  const base = `/dossiers/${target.application}`;
  const before = await api(`/applications/${target.application}/dossier`);
  const original = before.parsed_data.structured.identity.name.value;
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [], viewports = [];
  try {
    const page = await browser.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://localhost:5173');
    await page.waitForSelector('#root > *');
    async function mount(mode) {
      await page.evaluate(async ({ token, target, mode }) => {
        const source = await (await fetch('/src/components/CandidateDossier.tsx')).text();
        const queryPath = source.match(/from ["']([^"']*react-query[^"']*)["']/)[1];
        const [{ default: React }, { default: DOM }, RQ, { default: Dossier }, { default: Batch }] = await Promise.all([
          import('/node_modules/.vite/deps/react.js'), import('/node_modules/.vite/deps/react-dom_client.js'), import(queryPath), import('/src/components/CandidateDossier.tsx'), import('/src/components/DossierBatchWorkspace.tsx'),
        ]);
        localStorage.setItem('ats_smart_access_token', token);
        document.getElementById('root').style.display = 'none';
        if (!window.phase6Root) {
          const host = document.createElement('div');
          host.className = 'min-h-screen bg-paper p-5 text-ink'; host.dir = 'rtl'; document.body.append(host);
          window.phase6Root = DOM.createRoot(host);
          window.phase6Query = new RQ.QueryClient({ defaultOptions: { queries: { retry: false } } });
        }
        const child = mode === 'batch' ? React.createElement(Batch, { jobId: target.job }) : React.createElement(Dossier, { application: { application_id: target.application, candidate_name: 'نمونهٔ ساختگی — حساب آزمایشی', current_status: 'Draft', score_ai: null, updated_at: '2026-11-16T00:00:00Z' }, onClose: () => { window.fixtureClosed = true; } });
        window.phase6Root.render(React.createElement(RQ.QueryClientProvider, { client: window.phase6Query }, child));
      }, { token, target, mode });
    }
    await mount('dossier');
    const panel = page.getByRole('region', { name: 'بازبینی انسانی پرونده' });
    await panel.getByLabel('در فهرست بررسی منتخب تیم باشد').waitFor();
    await panel.getByLabel('دلیل ثبت یا اصلاح').fill('بازبینی منبع ساختگی برای آزمون محلی');
    await panel.getByText('اصلاح مستند یک فیلد', { exact: true }).click();
    await panel.getByLabel('فیلد منبع').selectOption('identity.name');
    await panel.getByLabel('مقدار تصحیح‌شده').fill('Mira Hart');
    await panel.getByLabel('شاهد متنی یا توضیح محل بررسی در سند').fill('صفحهٔ اول نمونهٔ ساختگی: MIRA HART');
    await panel.getByRole('button', { name: 'ثبت اصلاح انسانی', exact: true }).click();
    await panel.getByText('بازبینی در سرور ذخیره شد.', { exact: true }).waitFor();
    await panel.getByLabel('در فهرست بررسی منتخب تیم باشد').click();
    await page.waitForFunction(async ({ origin, token, id }) => {
      const r = await fetch(`${origin}/dossiers/${id}/review`, { headers: { Authorization: `Bearer ${token}` } }); return (await r.json()).shortlisted === true;
    }, { origin, token, id: target.application });
    await panel.getByText('یادداشت و بازخورد', { exact: true }).click();
    await panel.getByLabel('متن یادداشت').fill('یادداشت خصوصی ساختگی برای بررسی محلی');
    await panel.getByRole('button', { name: 'ذخیره یادداشت', exact: true }).click();
    await panel.getByText('یادداشت خصوصی ساختگی برای بررسی محلی', { exact: true }).waitFor();
    await panel.getByText('پیش‌نویس درخواست تکمیل اطلاعات', { exact: true }).click();
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => document.documentElement.classList.toggle('dark', theme === 'dark'), theme);
      for (const width of [375, 768, 1440]) {
        await page.setViewportSize({ width, height: 1000 });
        await panel.scrollIntoViewIfNeeded();
        const overflow = await page.getByRole('dialog').evaluate(el => ({ page: document.documentElement.scrollWidth > innerWidth, dialog: el.scrollWidth > el.clientWidth + 1 }));
        if (overflow.page || overflow.dialog) throw Error('review horizontal overflow');
        await page.screenshot({ path: path.join(out, `synthetic-${prefix}-review-${theme}-${width}.png`) });
        viewports.push({ theme, width, overflow });
      }
    }
    const reviewed = await api(base + '/review');
    if (reviewed.effective_parsed.structured.identity.name.value !== 'Mira Hart' || reviewed.notes.length !== 1 || !reviewed.shortlisted) throw Error('review persistence failed');
    await mount('batch');
    await page.getByRole('heading', { name: 'بررسی گروهی پرونده‌ها', exact: true }).waitFor();
    await page.getByRole('list').first().getByRole('checkbox').first().check();
    await page.getByRole('button', { name: 'مقایسهٔ شواهد منتخب‌ها' }).click();
    await page.getByRole('heading', { name: 'مقایسهٔ مستند', exact: true }).waitFor();
    await page.getByLabel('فیلتر شواهد').selectOption('unknown');
    await page.getByLabel('فیلتر شواهد').selectOption('all');
    await page.getByRole('button', { name: 'صف‌گیری تحلیل مجدد منتخب‌ها', exact: true }).click();
    await page.getByRole('heading', { name: 'پیشرفت تحلیل گروه', exact: true }).waitFor();
    const started = Date.now(); let state;
    for (let i = 0; i < 90; i++) {
      state = (await api(`/applications/${target.application}/dossier`)).processing_state;
      if (state.status === 'succeeded') break;
      if (state.status === 'failed' || state.status === 'retrying') throw Error(`synthetic reanalysis ${state.status}: ${state.error_code || 'unknown'}`);
      if (i % 10 === 0) console.log(JSON.stringify({ synthetic: true, reanalysis: state.status, elapsed_s: Math.round((Date.now() - started) / 1000) }));
      await page.waitForTimeout(2000);
    }
    if (state.status !== 'succeeded') throw Error('bounded synthetic reanalysis wait exceeded');
    const reanalysisSeconds = Math.round((Date.now() - started) / 1000);
    await page.getByRole('button', { name: 'تازه‌سازی پیشرفت' }).click();
    const after = await api(`/applications/${target.application}/dossier`);
    const afterReview = await api(base + '/review');
    const versions = await api(base + '/versions');
    if (after.parsed_data.structured.identity.name.value !== original) throw Error('human edit modified original model data');
    if (afterReview.effective_parsed.structured.identity.name.value !== 'Mira Hart' || !afterReview.corrections[0].applicable) throw Error('human correction lost after real model run');
    if (!versions.items.length) throw Error('successful worker did not record snapshot');
    await api(base + `/versions/compare?left=${versions.items[0].id}&right=${versions.items[0].id}`);
    await page.getByRole('button', { name: 'مقایسهٔ شواهد منتخب‌ها' }).click();
    await page.getByRole('heading', { name: 'مقایسهٔ مستند', exact: true }).waitFor();
    for (const width of [375, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      if (overflow) throw Error('batch horizontal overflow');
      await page.screenshot({ path: path.join(out, `synthetic-${prefix}-batch-${width}.png`), fullPage: true });
    }
    await mount('dossier');
    await panel.getByText('تاریخچهٔ ثبت‌ها و نسخه‌های تحلیل', { exact: true }).click();
    await panel.getByLabel('نسخهٔ اول').locator(`option[value="${versions.items[0].id}"]`).waitFor({ state: 'attached' });
    await panel.getByLabel('نسخهٔ اول').selectOption(versions.items[0].id);
    await panel.getByLabel('نسخهٔ دوم').selectOption(versions.items[0].id);
    await panel.getByRole('button', { name: 'مقایسهٔ دو نسخه' }).click();
    await panel.getByText(/سیاست تحلیل و آگهی یکسان است/).waitFor();
    for (const width of [375, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await panel.getByLabel('نسخهٔ اول').scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(out, `synthetic-${prefix}-versions-${width}.png`) });
    }
    await page.getByRole('button',{name:'پنهان‌کردن اطلاعات هویتی'}).click();
    const masked=page.getByRole('dialog',{name:'مرور بدون نمایش هویت'});
    const maskedText=await masked.innerText();
    if(maskedText.includes('MIRA HART')||maskedText.includes('Mira Hart')||maskedText.includes('نمونهٔ ساختگی — حساب آزمایشی'))throw Error('identity remained in masked dossier');
    await page.emulateMedia({reducedMotion:'reduce'});
    for(let i=0;i<12;i++){await page.keyboard.press('Tab');if(!await masked.evaluate(el=>el.contains(document.activeElement)))throw Error('focus escaped masked dialog');}
    for(const width of [375,1440]){await page.setViewportSize({width,height:1000});await page.screenshot({path:path.join(out,`synthetic-${prefix}-identity-hidden-${width}.png`)});}
    if (errors.length) throw Error('browser runtime errors');
    const result = { synthetic: true, live_api: true, real_model_reanalysis: true, preserved_original: true, correction_survived: true, private_note_persisted: true, shortlisted: true, snapshots: versions.items.length, reanalysis_seconds: reanalysisSeconds,identity_hidden:true,masked_focus_trap:true,reduced_motion:true, runtime_errors: 0, viewports };
    fs.writeFileSync(path.join(out, 'browser-live.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
