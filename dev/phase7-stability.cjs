// فشار محدود فقط روی fixture ساختگیِ شناسه‌دار؛ هیچ پروندهٔ واقعی دوباره تحلیل نمی‌شود.
const fs=require('node:fs'),cp=require('node:child_process'),path=require('node:path');
const out=path.resolve('training/reports/phase7');
const target=JSON.parse(fs.readFileSync(path.join(out,'target.json'),'utf8'));
if(target.synthetic!==true)throw Error('synthetic fixture required');
const origin='http://localhost:8000/api/v1';
const containers=['ats-editorial-preview-api-1','ats-editorial-preview-resume-worker-1','ats-inference-local-ats-engine-1'];
function command(exe,args,input){const r=cp.spawnSync(exe,args,{input,encoding:'utf8',timeout:15000,windowsHide:true});if(r.status!==0)throw Error('local measurement command failed');return r.stdout;}
function memory(){
  const rows=command('docker',['stats','--no-stream','--format','{{json .}}',...containers]).trim().split(/\r?\n/).map(JSON.parse).map(r=>({container:r.Name,memory:r.MemUsage,cpu:r.CPUPerc}));
  let gpu=null;try{gpu=command('nvidia-smi',['--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits']).trim();}catch{}
  return {containers:rows,gpu_memory_mib_and_utilization:gpu};
}
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const quantile=(values,p)=>{const x=[...values].sort((a,b)=>a-b);return Math.round(x[Math.max(0,Math.ceil(x.length*p)-1)]*10)/10;};
(async()=>{
 const keys=JSON.parse(fs.readFileSync('secrets/editorial-local.json','utf8'));
 const login=await fetch(origin+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'hr@ats-preview.example.com',password:keys.demo})});
 if(!login.ok)throw Error('fixture authentication failed');const token=(await login.json()).access_token;
 const headers={Authorization:`Bearer ${token}`,'Content-Type':'application/json'};
 async function api(route,body){const r=await fetch(origin+route,{headers,...(body?{method:'POST',body:JSON.stringify(body)}:{})});if(!r.ok)throw Error('fixture API status '+r.status);return r.json();}
 const review=`/dossiers/${target.application}/review`,dossier=`/applications/${target.application}/dossier`;
 const state=await api(review),fact=state.targets.find(t=>t.target==='identity.name');
 await api(`/dossiers/${target.application}/events`,{action:'correction',expected_revision:state.revision,reason:'Synthetic stability review',target:fact.target,source_hash:state.source_hash,anchor:fact.anchor,value:'Mira Hart',evidence_text:'Page 1 synthetic source'});
 const cold={measured:false,scope:'engine process restart; filesystem cache is not cleared'};
 const idleCode="import json;from redis import Redis;from rq import Queue;from rq.registry import StartedJobRegistry;from app.core.config import settings;c=Redis.from_url(settings.REDIS_URL);print(json.dumps(dict(queued=Queue('resumes',connection=c).count,started=StartedJobRegistry('resumes',connection=c).count)))";
 const idle=JSON.parse(command('docker',['exec','-e','PYTHONPATH=/app','ats-editorial-preview-resume-worker-1','python','-c',idleCode]));
 if(idle.queued===0&&idle.started===0){
  const start=performance.now();command('docker',['restart','ats-inference-local-ats-engine-1']);
  for(let i=0;i<45;i++){try{const r=await fetch('http://localhost:11435/health',{signal:AbortSignal.timeout(1500)});if(r.ok){cold.measured=true;cold.ready_ms=Math.round(performance.now()-start);break;}}catch{}await pause(500);}
  if(!cold.measured)throw Error('bounded engine readiness exceeded');
 }else cold.reason='existing local queue not idle; restart skipped';
 const memorySamples=[memory()],responses=[];
 async function probe(route){const start=performance.now();const r=await fetch(origin+route,{headers,signal:AbortSignal.timeout(15000)});await r.arrayBuffer();responses.push({kind:route.includes('/document/')?'preview':route.endsWith('/review')?'review':'dossier',status:r.status,ms:performance.now()-start});if(![200,429,503].includes(r.status))throw Error('unexpected concurrent status '+r.status);}
 for(let wave=0;wave<3;wave++)await Promise.all(Array.from({length:12},(_,i)=>probe(i%3===0?`/applications/${target.application}/document/1`:i%3===1?review:dossier)));
 const runs=[];
 for(let run=0;run<3;run++){
  const start=performance.now();const batch=await api('/dossiers/batches',{application_ids:[target.application]});let complete=false;
  for(let i=0;i<120;i++){
   const result=await api(dossier),s=result.processing_state;
   if(s.status==='succeeded'){complete=true;break;}
   if(['failed','retrying'].includes(s.status))throw Error('synthetic model run '+s.status);
   await probe(review);await pause(500);
  }
  if(!complete)throw Error('bounded model run exceeded');
  const protectedState=await api(review);if(protectedState.effective_parsed.structured.identity.name.value!=='Mira Hart')throw Error('correction lost');
  const original=await api(dossier);if(original.parsed_data.structured.identity.name.value!=='MIRA HART')throw Error('source mutated');
  const progress=await api('/dossiers/batches/'+batch.batch_id);if(progress.items[0].processing.status!=='succeeded')throw Error('batch state mismatch');
  runs.push({run:run+1,scope:run===0?'first inference after engine restart':'warm engine',queue_to_observed_success_ms:Math.round(performance.now()-start),protected_correction:true});
  memorySamples.push(memory());console.log(JSON.stringify(runs[runs.length-1]));
 }
 const statuses={};for(const r of responses)statuses[r.status]=(statuses[r.status]||0)+1;
 const report={synthetic:true,production_touched:false,cold,burst_concurrency:12,burst_waves:3,requests:responses.length,statuses,
  p50_ms:quantile(responses.map(r=>r.ms),.5),p95_ms:quantile(responses.map(r=>r.ms),.95),max_ms:Math.round(Math.max(...responses.map(r=>r.ms))),runs,memorySamples,
  limitations:['bounded_local_run_not_capacity_certification','no_long_duration_leak_proof','not_production_latency','no_model_quality_claim']};
 fs.writeFileSync(path.join(out,'stability.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({requests:report.requests,statuses,p95_ms:report.p95_ms,cold}));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
