import {useEffect,useRef,useState} from 'react';
import {fetchApplicationDocument,type DocumentPage} from '../services/applicationsApi';
import {useEvidence} from './EvidenceContext';
import {object,text} from './dossierData';

export default function DocumentEvidencePane({applicationId,layout}:{applicationId:string;layout:unknown}) {
  const evidence=useEvidence(),selection=evidence?.selection;
  const [opened,setOpened]=useState(false),[page,setPage]=useState(1),[attempt,setAttempt]=useState(0);
  const [data,setData]=useState<DocumentPage|null>(null),[error,setError]=useState(false),[loading,setLoading]=useState(false);
  const [zoom,setZoom]=useState(1),highlight=useRef<HTMLDivElement>(null);
  const panel=useRef<HTMLElement>(null),hash=text(object(layout).file_sha256);
  useEffect(()=>{
    if(!selection)return;
    setOpened(true);setPage(selection.reference.page||1);
    panel.current?.scrollIntoView?.({block:'nearest',behavior:'instant'});
  },[selection]);
  useEffect(()=>{
    setData(null);setError(false);
    if(!opened)return;
    const controller=new AbortController();let active=true;setLoading(true);
    fetchApplicationDocument(applicationId,page,hash,controller.signal).then(result=>{
      if(active){setData(result);setLoading(false);}
    }).catch(()=>{if(active&&!controller.signal.aborted){setError(true);setLoading(false);}});
    return ()=>{active=false;controller.abort();};
  },[applicationId,page,hash,opened,attempt]);
  const reference=selection?.reference,box=reference?.bbox;
  const pageLayouts=Array.isArray(object(layout).pages)?(object(layout).pages as unknown[]).map(object):[];
  const geometry=pageLayouts.find(p=>p.number===data?.page);
  const geometryMatches=!!data&&!!hash&&data.file_sha256===hash&&data.coordinate_space==='unrotated_crop_points'&&geometry?.coordinate_space==='unrotated_crop_points'&&geometry.width===data.width&&geometry.height===data.height;
  const validBox=geometryMatches&&reference?.page===data.page&&Array.isArray(box)&&box.length===4&&box.every(Number.isFinite)&&box[0]>=0&&box[1]>=0&&box[2]>box[0]&&box[3]>box[1]&&box[2]<=data.width&&box[3]<=data.height;
  useEffect(()=>{if(validBox)highlight.current?.scrollIntoView?.({block:'center',inline:'nearest',behavior:'instant'});},[data,selection,validBox]);
  return <section ref={panel} className="editorial-panel min-w-0" aria-label="سند و شاهد انتخاب‌شده">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-heading">سند و شاهد انتخاب‌شده</h3><button type="button" onClick={()=>setOpened(v=>!v)} aria-expanded={opened} className="rounded border border-rule px-3 py-2 text-caption">{opened?'بستن پیش‌نمایش':'نمایش PDF'}</button></div>
    {reference&&<div className="my-3 border-s-2 border-rule ps-3"><p role="status" className="text-caption">{reference.page?`شاهد انتخاب‌شده در صفحهٔ ${reference.page.toLocaleString('fa-IR')}`:'شاهد متنی؛ شمارهٔ صفحه در داده موجود نیست.'}</p><p className="reading-copy text-caption" dir="auto">{reference.text}</p></div>}
    {opened&&<>
      {loading&&<p role="status" className="my-3 text-caption">در حال دریافت صفحهٔ سند…</p>}
      {error&&<div role="alert" className="my-3 text-caption">پیش‌نمایش دریافت نشد؛ ممکن است فایل PDF نباشد، نسخهٔ فایل عوض شده باشد یا دسترسی آن فراهم نباشد. شاهد متنی بالا همچنان قابل بررسی است. <button onClick={()=>setAttempt(v=>v+1)} className="underline">تلاش مجدد برای سند</button></div>}
      {data&&<>
        <div className="my-3 flex flex-wrap items-center gap-3 text-caption"><button disabled={page<=1} onClick={()=>setPage(p=>p-1)} className="rounded border border-rule px-3 py-2 disabled:opacity-40">صفحهٔ قبل</button><span aria-live="polite">صفحهٔ {data.page.toLocaleString('fa-IR')} از {data.pages.toLocaleString('fa-IR')}</span><button disabled={page>=data.pages} onClick={()=>setPage(p=>p+1)} className="rounded border border-rule px-3 py-2 disabled:opacity-40">صفحهٔ بعد</button></div>
        <div className="mb-3 flex flex-wrap items-center gap-3 text-caption"><button disabled={zoom<=1} onClick={()=>setZoom(z=>Math.max(1,z-.5))} className="rounded border border-rule px-3 py-2 disabled:opacity-40">کوچک‌نمایی سند</button><span>{(zoom*100).toLocaleString('fa-IR')}٪</span><button disabled={zoom>=2} onClick={()=>setZoom(z=>Math.min(2,z+.5))} className="rounded border border-rule px-3 py-2 disabled:opacity-40">بزرگ‌نمایی سند</button></div>
        <div className="max-h-[65dvh] max-w-full overflow-auto rounded border border-rule bg-white" tabIndex={0} role="region" aria-label="تصویر قابل پیمایش سند">
        <div className="relative min-w-full" style={{width:`${zoom*100}%`}} dir="ltr">
          <img src={data.image.startsWith('data:image/png;base64,')?data.image:undefined} alt={`تصویر صفحهٔ ${data.page}؛ متن قابل خواندن در بخش متن رزومه و شاهدها موجود است.`} className="block h-auto w-full"/>
          {validBox&&<div ref={highlight} data-testid="evidence-highlight" aria-hidden="true" className="pointer-events-none absolute border-2 border-amber-600 bg-amber-300/30" style={{left:`${box[0]/data.width*100}%`,top:`${box[1]/data.height*100}%`,width:`${(box[2]-box[0])/data.width*100}%`,height:`${(box[3]-box[1])/data.height*100}%`}}/>}
        </div>
        </div>
        {reference&&!validBox&&<p className="mt-2 text-caption text-muted">مختصات معتبر و هم‌نسخه برای این شاهد موجود نیست؛ محل آن روی تصویر حدس زده نمی‌شود.</p>}
      </>}
    </>}
  </section>;
}
