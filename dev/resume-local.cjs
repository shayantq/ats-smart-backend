// فقط چرخهٔ عمر ATS محلی؛ رازها خوانده می‌شوند و هرگز چاپ نمی‌شوند.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const root = path.resolve(__dirname, '..');
process.chdir(root);
const keys = JSON.parse(fs.readFileSync('secrets/editorial-local.json', 'utf8'));
const env = {...process.env, LOCAL_PG_PASSWORD:keys.pg, ATS_LOCAL_ROOT:root.replaceAll('\\', '/'),
  INFERENCE_LOAD_MODE:'mmap', INFERENCE_SPEC_TYPE:'ngram-cache', INFERENCE_STATIC_CACHE:'/lookup/train-original.bin'};
const local = ['compose','-f','dev/compose.local.yml','-f','dev/compose.resume-local.yml','--profile','resume-worker'];
const model = ['compose','-f','inference/compose.yml','-f','inference/compose.decode.yml','-f','inference/compose.hybrid.yml','-f','inference/compose.diagnosis.yml'];
function run(args) {
  const result = cp.spawnSync('docker', args, {env, encoding:'utf8', timeout:90000, windowsHide:true});
  let output = (result.stdout || '') + (result.stderr || '');
  for (const value of Object.values(keys)) if (typeof value === 'string') output = output.replaceAll(value, '[redacted]');
  process.stdout.write(output);
  if (result.status !== 0) throw Error('local Docker command failed');
}
async function main() {
  const action = process.argv[2] || 'status';
  if (action === 'status') {run([...local,'ps']); run([...model,'ps']); return;}
  if (action === 'stop') {run([...local,'stop','resume-worker','api']); run([...model,'stop']); return;}
  if (!['up','api','worker'].includes(action)) throw Error('use up, api, worker, status or stop');
  for (const file of ['secrets/editorial-docker.env','secrets/inference/worker.pem','secrets/inference/public/worker.pem']) {
    if (!fs.existsSync(file)) throw Error('required local secret file missing');
  }
  if (action !== 'worker') run([...local,'up','-d','--no-build','--pull','never','api']);
  if (action === 'api') return;
  run([...model,'up','-d','--no-build','--pull','never']);
  let ready = false;
  for (let i=0; i<30; i++) {
    try {if ((await fetch('http://127.0.0.1:8081/ready',{signal:AbortSignal.timeout(2000)})).ok) {ready=true; break;}} catch {}
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  if (!ready) throw Error('local model not ready; worker was not started');
  // Compose فقط همین یک سرویس را مدیریت می‌کند؛ اجرای دوباره Worker موازی نمی‌سازد.
  run([...local,'up','-d','--no-deps','--no-build','--pull','never','resume-worker']);
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
