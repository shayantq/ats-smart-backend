# استقرار روی Kubernetes

مهاجرت کامل ATS Smart از Docker Compose به Kubernetes برای مقیاس‌دهی خودکار و دسترس‌پذیری بالا. همان ایمیج‌های Compose بدون هیچ تغییری استفاده می‌شوند. ساختار مانیفست‌ها با **Kustomize** است که داخل خودِ `kubectl` وجود دارد و ابزار اضافه‌ای لازم ندارد.

```bash
bash k8s/deploy.sh        # استقرار/به‌روزرسانی کامل (Secret ها، ایمیج‌ها، metrics-server، Ingress Controller، مانیفست‌ها)
bash k8s/verify.sh        # بررسی خودکار معیارهای پذیرش مهاجرت — خروجی نهایی: [ACCEPTANCE PASS]
bash k8s/hpa-stress.sh    # تست بار + بررسی Scale Up / Scale Down و توزیع بار Ingress — [HPA & INGRESS PASS]
bash k8s/queue-stress.sh  # ایمیل انبوه + پردازش رزومه هم‌زمان، بدون از دست رفتن کار — [QUEUE STRESS PASS]
bash k8s/search-benchmark.sh  # سنجش ایندکس‌های GIN جستجوی کارجویان روی ۲۰٬۰۰۰ رزومه — [GIN INDEX PASS]
bash k8s/genai-poc.sh     # اثبات مفهوم تولید سؤال مصاحبه از مسیر کامل API — [GENAI POC PASS]
```

| آدرس (محیط لوکال) | سرویس |
|---|---|
| http://localhost:8081 | سایت — از طریق NGINX Ingress Controller |
| http://localhost:3030 | Grafana — کاربر/رمز در `k8s/overlays/local/secrets/grafana.env` (داشبورد «کلاستر Kubernetes») |
| http://localhost:8025 | Mailpit — سرور SMTP آزمایشی؛ همه‌ی ایمیل‌های محیط لوکال اینجا دیده می‌شوند |
| `kubectl -n ats-smart port-forward svc/prometheus 9091:9090` ← http://localhost:9091 | Prometheus (فقط داخل کلاستر) |

پورت‌ها عمداً با Docker Compose (8080، 3000، 8088) و پورت 80 ویندوز (سرویس سیستمی http.sys) تداخل ندارند و هر دو محیط می‌توانند هم‌زمان اجرا شوند.

---

## معماری

```
        مرورگر ── :8081 ──► Service nginx-ingress (LoadBalancer) ──► NGINX Ingress Controller ×2..4 (HPA)
                                                                    │ least_conn · retry · health check
                                    ┌───────────── /  ──────────────┴──────── /api ، /media ─────────┐
                                    ▼                                                                ▼
                         frontend Pod ×2..4 (HPA)                                  backend-api Pod ×2..6 (HPA: CPU/RAM ۷۵٪)
                                                                                   │          │       │
                worker ×1..4 (ایمیل‌ها) · resume-worker ×1..4 (رزومه‌ها) ─────────┼──────────┼── PVC media (RWX)
                                         scheduler                                 │          │
                                      ▼            ▼
                       Service postgres     Service redis
                              │                    │
                    StatefulSet postgres-0     Deployment redis
                    PVC data-postgres-0        PVC redis-data (AOF)
                    PVC wal-archive-postgres-0 ──► backup (همان Node) ──► Offsite (رمزنگاری‌شده)

   Prometheus (Kubernetes SD) ◄── /metrics همه‌ی Pod ها + exporter ها ──► Alertmanager ──► /api/v1/ops/alerts
   Grafana ◄── Prometheus                                                                (اعلان داخل سایت)
```

### ۱۰ سرویس و معادل‌شان در Compose

| # | سرویس Compose | منبع Kubernetes | نسخه‌ها | ذخیره‌سازی |
|---|---|---|---|---|
| 1 | `backend_api` | Deployment `backend-api` + Service + HPA + PDB | ۲ تا ۶ (HPA) | PVC `media` (RWX) |
| 2 | `worker` | Deployment `worker` (صف‌های notifications ← bulk ← default) + HPA | ۱ تا ۴ (HPA) | — |
| 2′ | (همان worker) | Deployment `resume-worker` (صف resumes، پردازش سنگین رزومه) + HPA | ۱ تا ۴ (HPA) | PVC `media` |
| 2″ | (همان worker) | Deployment `genai-worker` (صف genai، تولید سؤال مصاحبه با مدل زبانی) | ۱ | — |
| 3 | `scheduler` | Deployment `scheduler` (Recreate) | همیشه ۱ | — |
| 4 | `frontend` | Deployment `frontend` + Service + HPA + PDB | ۲ تا ۴ (HPA) | — |
| 5 | `postgres_db` | **StatefulSet** `postgres` + Service + Headless Service | ۱ | volumeClaimTemplates: `data`، `wal-archive` |
| 6 | `redis_cache` | Deployment `redis` (Recreate) + Service | ۱ | PVC `redis-data` |
| 7 | `prometheus` | Deployment + Service + ServiceAccount/Role | ۱ | PVC `prometheus-data` |
| 8 | `alertmanager` | Deployment + Service | ۱ | PVC `alertmanager-data` |
| 9 | `grafana` | Deployment + Service | ۱ | PVC `grafana-data` |
| 10 | `backup` | Deployment `backup` (Recreate) | ۱ | PVC `backup-metrics` + WAL مشترک |
| — | `postgres_exporter` · `redis_exporter` | Sidecar داخل Pod همان سرویس | — | — |
| — | `node_exporter` | **DaemonSet** (یک نسخه روی هر Node) | — | — |
| — | (جدید) | `kube-state-metrics` — وضعیت اشیای کلاستر برای Prometheus | ۱ | — |
| — | (فقط لوکال) | `mailpit` — سرور SMTP آزمایشی (`overlays/local/mailpit.yaml`) | ۱ | — |
| — | (فقط لوکال، اختیاری) | `genai-inference` — سرور مدل زبانی متن‌باز روی CPU (`overlays/local/genai-inference`؛ نشانی وزن‌ها در `model.env` محلی) | ۱ | PVC `genai-models` |
| — | `gateway` (Nginx لبه) | **NGINX Ingress Controller** (`k8s/addons/nginx-ingress`) + Ingress `ats-smart` | ۲ تا ۴ (HPA) | — |
| — | `migrate` | **Job** یک‌باره (پیش از بالا آمدن API/Worker) | — | — |
| — | `backup_restore` | CronJob معلق `backup-drill` (فقط اجرای دستی) | — | — |
| — | `offsite_storage` | فقط لوکال: PVC `offsite` (ریموت rclone از نوع local) | — | — |

---

## ساختار پوشه

```
k8s/
├── base/                       # مستقل از محیط
│   ├── kustomization.yaml      # فهرست منابع + ConfigMap Generator ها
│   ├── namespace.yaml          # Namespace «ats-smart»
│   ├── config/app.env          # تنظیمات غیرحساس برنامه ← ConfigMap «ats-config»
│   ├── postgres/               # StatefulSet، Service ها، pg_hba.conf
│   ├── redis/redis.yaml        # Deployment + Service + PVC
│   ├── backend/                # backend-api، worker، scheduler، Job مایگریشن، PVC رزومه‌ها
│   ├── frontend/frontend.yaml
│   ├── hpa.yaml                # مقیاس‌دهی خودکار بک‌اند و فرانت‌اند
│   ├── monitoring/             # Prometheus (+RBAC)، Alertmanager، Grafana، node-exporter + پیکربندی‌های K8s
│   └── backup/                 # سرویس backup، CronJob تمرین بازیابی، backup.env
├── overlays/local/             # Docker Desktop: StorageClass با Retain، پورت 8081 Ingress، Secret ها، Offsite محلی
│   └── secrets/*.env.example   # نمونه‌ی Secret ها (فایل‌های واقعی *.env در .gitignore)
├── addons/metrics-server/      # منبع متریک HPA (آینه‌ی Docker Hub، چون registry.k8s.io از ایران 403 می‌دهد)
├── addons/nginx-ingress/       # NGINX Ingress Controller (ورودی واحد ترافیک، توزیع بار در سطح Pod)
├── loadtest/                   # سناریوی Locust و Job تست بار HPA (hpa-stress.sh)
├── deploy.sh · verify.sh · hpa-stress.sh · queue-stress.sh · search-benchmark.sh
└── .release/                   # تولیدی deploy.sh (تگ ایمیج همین انتشار) — در .gitignore
monitoring/kustomization.yaml   # ConfigMap قوانین هشدار و داشبوردها از همان فایل‌های Compose
```

قوانین هشدار (`monitoring/prometheus/alerts.yml`) و داشبوردهای Grafana **یک منبع حقیقت** دارند و بین Compose و Kubernetes مشترک‌اند. نام Job های Prometheus هم در Kubernetes همان نام‌های Compose است.

---

## راه‌اندازی

پیش‌نیاز: یک کلاستر Kubernetes و `kubectl`. در محیط لوکال: Docker Desktop ← Settings ← Kubernetes ← **Enable Kubernetes** (kubeadm، یک Node).

`deploy.sh` به ترتیب این کارها را انجام می‌دهد:

1. **بررسی کلاستر:** Overlay لوکال فقط روی context `docker-desktop` اعمال می‌شود. برای عبور از این محدودیت: `ALLOW_ANY_CONTEXT=1`.
2. **Secret ها:** در اولین اجرا، `secrets/*.env` با رمزهای تصادفی امن ساخته می‌شوند. کلید عمومی بک‌آپ همان `backup/secrets/public/age-recipient.txt` نسخه‌ی Compose است.
3. **ایمیج‌ها:** تگ `sha-<کامیت جاری>` (همان قرارداد CI/CD). اگر ایمیج موجود نباشد، ساخته می‌شود. Docker Desktop از Image Store همان موتور داکر استفاده می‌کند، پس به Registry نیازی نیست.
4. **metrics-server:** اگر کلاستر از قبل ندارد، نصب می‌شود.
5. **اعمال مانیفست‌ها:** `kubectl apply -k`. ConfigMap/Secret های هش‌دار قدیمی با Prune پاک می‌شوند.
6. **انتظار:** برای پستگرس، Job مایگریشن و Rollout هر سرویس.

| متغیر | کاربرد |
|---|---|
| `IMAGE_TAG=sha-1a2b3c4` | تگ دلخواه |
| `FORCE_BUILD=1` | ساخت دوباره‌ی ایمیج‌ها (مثلاً با تغییرات Commit‌نشده) |
| `SKIP_BUILD=1` | بدون ساخت ایمیج، با تگ‌های `:local` |
| `SKIP_ADDONS=1` | بدون metrics-server |
| `DEBIAN_MIRROR=https://deb.debian.org` | برای شبکه‌ی ناپایدار هنگام ساخت ایمیج بک‌اند |

بدون اسکریپت: فایل‌های `secrets/*.env` را از روی نمونه‌ها بسازید و بعد `kubectl apply -k k8s/overlays/local` را اجرا کنید (با ایمیج‌های `:local` از `docker compose build`).

---

## ذخیره‌سازی پایدار PostgreSQL (PV / PVC)

```
Pod postgres-0 ──► PVC data-postgres-0 ──► PV pvc-… (reclaimPolicy: Retain) ──► دیسک (StorageClass ats-retain)
```

- **StatefulSet:** Pod همیشه `postgres-0` است و بعد از هر ری‌استارت، از کار افتادن یا انتقال، دقیقاً به همان PVC های قبلی‌اش وصل می‌شود. هرگز دو نسخه هم‌زمان روی یک پوشه‌ی داده نمی‌نویسند.
- **volumeClaimTemplates:** یک PVC اختصاصی برای داده (۵Gi) و یکی برای آرشیو WAL (۲Gi). PV ها را Dynamic Provisioning می‌سازد.
- **سه لایه محافظت در برابر حذف:**
  1. `persistentVolumeClaimRetentionPolicy: Retain`: حذف StatefulSet یا کاهش نسخه‌ها، PVC را پاک نمی‌کند.
  2. StorageClass `ats-retain` با `reclaimPolicy: Retain`: حذف PVC هم، PV و داده‌ی روی دیسک را پاک نمی‌کند (وضعیت PV می‌شود `Released`).
  3. بک‌آپ رمزنگاری‌شده‌ی Offsite (سرویس `backup`).
- `PGDATA` یک زیرپوشه است (`/var/lib/postgresql/data/pgdata`)، چون ریشه‌ی دیسک‌های ابری `lost+found` دارد.

آزمون (`verify.sh`): یک نشانگر در دیتابیس جدای `k8s_persistence_check` نوشته می‌شود (به جداول برنامه و Alembic دست نمی‌زند). سپس Pod پستگرس حذف می‌شود؛ با `--deep` کل StatefulSet هم حذف و دوباره ساخته می‌شود. در پایان بررسی می‌شود که Pod جدید با UID متفاوت به همان PV وصل شده و نشانگر و داده‌های برنامه سالم مانده‌اند.

**اتصال دوباره به یک PV با وضعیت Released** (اگر PVC اشتباهی حذف شد):

```bash
kubectl patch pv <pv-name> -p '{"spec":{"claimRef":null}}'                    # PV دوباره Available می‌شود
# سپس PVC جدیدی با همان نام/اندازه و spec.volumeName: <pv-name> بسازید (یا deploy.sh را اجرا کنید)
```

---

## شبکه، پیکربندی و Secret ها

- **DNS داخلی:** هر سرویس با نام Service خودش در دسترس است: `postgres:5432`، `redis:6379`، `backend-api:8000`، `prometheus:9090`، `alertmanager:9093`.
  - Headless Service `postgres-headless` هویت پایدار `postgres-0.postgres-headless` را می‌سازد.
  - پورت دیتابیس و Redis هرگز بیرون از کلاستر باز نیست.
- **فرانت‌اند:** Nginx با متغیرهای `BACKEND_UPSTREAM` و `NGINX_RESOLVER` همان ایمیج به CoreDNS و نام کامل `backend-api.<ns>.svc.cluster.local` وصل می‌شود. resolver خودِ Nginx دامنه‌های جست‌وجو را اعمال نمی‌کند.
- **ConfigMap ها:**
  - `ats-config` (از `base/config/app.env` + `overlays/local/config.env`) — فقط برای کانتینرهای ایمیج بک‌اند
  - `postgres-config` (pg_hba + نام دیتابیس) — جدا، تا تغییر تنظیمات برنامه باعث ری‌استارت دیتابیس نشود
  - `backup-config`
  - پیکربندی‌های Prometheus/Alertmanager/pg_hba
  - قوانین هشدار و داشبوردها
- **Secret ها (حداقل دسترسی؛ هر مصرف‌کننده فقط Secret خودش):**

| Secret | کلیدها | مصرف‌کننده |
|---|---|---|
| `ats-postgres-secrets` | `POSTGRES_USER`، `POSTGRES_PASSWORD` | postgres، exporter، backup |
| `ats-backend-secrets` | `DATABASE_URL`، `SECRET_KEY`، `OPS_WEBHOOK_TOKEN`، `SMTP_*`، `S3_*` | backend-api، worker، migrate (و فقط کلید توکن در alertmanager) |
| `ats-grafana-secrets` | `GF_SECURITY_ADMIN_USER/PASSWORD` | grafana |
| `ats-backup-secrets` | `BACKUP_AGE_RECIPIENT`، کلیدهای Offsite | backup، backup-drill |
| `ats-genai-secrets` | `GENAI_BASE_URL`، `GENAI_MODEL`، `GENAI_API_KEY` (اختیاری — خالی = غیرفعال) | backend-api، genai-worker |

نام ConfigMap و Secret ها پسوند هش دارد. با تغییر هر مقدار و اجرای دوباره‌ی `deploy.sh`، Pod های مصرف‌کننده خودکار با مقدار جدید Rollout می‌شوند.

---

## مقیاس‌دهی خودکار و استقرار بدون قطعی

- **HPA** (`base/hpa.yaml`، منبع متریک: metrics-server). درصدها نسبت به `requests` هر کانتینر سنجیده می‌شوند:

| سرویس | نسخه‌ها | معیار Scale Up | Scale Down |
|---|---|---|---|
| backend-api | ۲ تا ۶ | CPU **یا** RAM بالای ۷۵٪ | ۲ دقیقه آرامش، سپس ۱ Pod در هر ۳۰ ثانیه |
| resume-worker (سرویس رزومه) | ۱ تا ۴ | CPU **یا** RAM بالای ۷۵٪ (OCR/NER رزومه‌ها) | ۳ دقیقه آرامش، ۱ Pod در دقیقه (Warm Shutdown کار در حال اجرا) |
| worker (ایمیل‌ها) | ۱ تا ۴ | CPU **یا** RAM بالای ۷۵٪ (ایمیل انبوه) | ۲ دقیقه آرامش، ۱ Pod در دقیقه |
| frontend | ۲ تا ۴ | CPU بالای ۷۵٪ (حافظه‌ی Nginx مستقل از ترافیک است) | ۲ دقیقه آرامش |
| nginx-ingress | ۲ تا ۴ | CPU بالای ۷۵٪ | ۲ دقیقه آرامش |

  - با دو متریک، HPA برای هر کدام تعداد لازم را حساب و بیشترین را انتخاب می‌کند: `⌈تعداد فعلی × مصرف ÷ ۷۵٪⌉`. افزایش بدون تأخیر است (هر ۳۰ ثانیه تا دو برابر یا ۲ Pod).
  - **request حافظه‌ی بک‌اند ۵۱۲Mi است.** مصرف پایه‌ی هر Pod پایتون (حدود ۲۰۰Mi ≈ ۴۰٪) با کم شدن ترافیک تقریباً ثابت می‌ماند؛ اگر نزدیک ۷۵٪ بود، طبق همین فرمول HPA هرگز Pod ها را کم نمی‌کرد.
  - سقف بک‌اند با ظرفیت اتصال‌های دیتابیس هماهنگ است: `(6+1) × 12 = 84 < 100`
  - Deployment های تحت HPA عمداً `replicas` ندارند تا `kubectl apply` تعداد تعیین‌شده توسط HPA را برنگرداند.
  - وضعیت: `kubectl -n ats-smart get hpa` و `kubectl top pods -n ats-smart`
- **RollingUpdate** با `maxUnavailable: 0`:
  - Pod جدید تا سبز شدن `readinessProbe` ترافیک نمی‌گیرد.
  - `preStop` (۵ ثانیه) فرصت حذف Pod از Endpoint ها را می‌دهد، و uvicorn درخواست‌های در حال اجرا را تا ۳۰ ثانیه کامل می‌کند.
  - **PodDisruptionBudget** حین تخلیه‌ی Node، حداقل یک نسخه را نگه می‌دارد.
- **مایگریشن‌ها:** Job `migrate` پیش از کد جدید اجرا می‌شود. initContainer `wait-for-migrations` در API و Worker تا رسیدن دیتابیس به `head` منتظر می‌ماند.
  - مایگریشن‌ها باید Expand/Contract باشند تا نسخه‌ی قبلی کد هم در حین انتشار با دیتابیس کار کند.
- **Probe ها:** `/api/v1/health` عمداً به دیتابیس و Redis وابسته نیست. قطعی موقت آن‌ها نباید همه‌ی Pod ها را از سرویس خارج یا ری‌استارت کند. بررسی عمیق اتصال‌ها با `/api/v1/health/ready` انجام می‌شود.

---

## Ingress و توزیع بار پیشرفته

ورودی واحد ترافیک کاربران **NGINX Ingress Controller** است (`k8s/addons/nginx-ingress`، ایمیج رسمی `nginx/nginx-ingress:5.7.0`؛ پروژه‌ی جامعه‌ی `ingress-nginx` از مارس ۲۰۲۶ بازنشسته شده و ایمیج‌هایش فقط روی `registry.k8s.io` است). Ingress برنامه (`base/ingress.yaml`) از الگوی **Mergeable** استفاده می‌کند: یک master برای دامنه و دو minion با تنظیمات جدا — `/api/` و `/media/` مستقیماً به Pod های بک‌اند، `/` به Pod های فرانت‌اند.

- **سطح Pod، نه ClusterIP:** Controller فهرست IP تک‌تک Pod های Ready را از EndpointSlice می‌خواند. هر Pod تازه‌ی HPA بلافاصله پس از Ready شدن سهم ترافیک می‌گیرد، و Pod در حال حذف قبل از خاموشی کنار گذاشته می‌شود (preStop).
- **`least_conn`:** هر درخواست به Pod با کمترین اتصال فعال می‌رود؛ Pod کند یا شلوغ خودکار سهم کمتری می‌گیرد.
- **بدون 502:** `proxy-next-upstream` (error / timeout / 502 / 503 / 504، تا ۳ بار): اگر Podی اتصال را رد کرد یا خطا داد، همان درخواست بی‌صدا به Pod سالم بعدی می‌رود. Health Check غیرفعال (`max-fails=1`، `fail-timeout=10s`) Pod خطادار را ۱۰ ثانیه کنار می‌گذارد. `keepalive` اتصال‌های باز به Pod ها را نگه می‌دارد.
- **IP واقعی کاربر:** Ingress لبه‌ی شبکه است و `X-Forwarded-For` را با IP اتصال **بازنویسی** می‌کند (نه الحاق به مقدار ارسالی کاربر)، و بک‌اند (`FORWARDED_ALLOW_IPS=*`، فقط از داخل کلاستر در دسترس) همان را می‌خواند. شمارنده‌ی Rate Limit هم در Redis مشترک است (`app/core/limiter.py`)؛ قبلاً هر Pod شمارنده‌ی جدا داشت و سقف واقعی «۵ × تعداد Pod ها» می‌شد.
- هدرهای امنیتی (CSP، X-Frame-Options و ...) برای پاسخ‌های API در خودِ Ingress اضافه می‌شوند — همان `frontend/security-headers.conf`.
- **متریک‌ها:** Prometheus (job `ingress`) زمان پاسخ و کد وضعیت را به تفکیک هر Pod مقصد جمع می‌کند (`nginx_ingress_controller_upstream_server_response_latency_ms_count{server, code}`).

### تست بار و HPA

```bash
bash k8s/hpa-stress.sh                         # پیش‌فرض: ۱۵۰ کاربر، ۱ دقیقه افزایش، ۳ دقیقه اوج
LOAD_USERS=250 LOAD_HOLD=300 bash k8s/hpa-stress.sh
```

یک Job Locust داخل کلاستر (`k8s/loadtest/`) سناریوی «انتشار آگهی پرطرفدار» را اجرا می‌کند: مرور مداوم فهرست آگهی‌ها، از مسیر واقعی کاربر (Service ورودی Ingress). اسکریپت ۴۰ آگهی آزمایشی از طریق خودِ API می‌سازد و در پایان پاکشان می‌کند. هر ۱۵ ثانیه وضعیت HPA ها ثبت می‌شود، و پس از پایان بار، تا برگشت بک‌اند به حداقل صبر می‌کند. بعد سه معیار را بررسی می‌کند: Scale Up، Scale Down، و پخش بار بین همه‌ی Pod ها با صفر 502. گزارش کامل در `k8s/loadtest/reports/` ذخیره می‌شود.

---

## صف‌های پس‌زمینه (Redis / RQ) و پایگاه داده

- **چهار صف با اولویت جدا** (`app/core/queue.py`):

| صف | محتوا | Worker | Timeout · تلاش مجدد |
|---|---|---|---|
| `notifications` | ایمیل‌های تراکنشی (OTP، تغییر وضعیت، پیشنهاد، یادآور مصاحبه) | `worker` — همیشه اول | ۲ دقیقه · ۳ بار (۳۰ث، ۲د، ۱۰د) |
| `bulk` | ایمیل انبوه (`enqueue_bulk`: هر ۵۰۰ کار با یک Pipeline) | `worker` — بعد از notifications | ۲ دقیقه · ۳ بار |
| `resumes` | پردازش سنگین رزومه (OCR ← NER ← مهارت ← نمره) | `resume-worker` (جدا) | ۵ دقیقه · ۲ بار |
| `default` | بقیه | `worker` | ۳ دقیقه · ۲ بار |

- **هیچ کاری از دست نمی‌رود:**
  - Worker با SIGTERM کار جاری را تمام می‌کند (`terminationGracePeriodSeconds` بیشتر از Timeout هر صف).
  - Worker ای که ناگهان از بین برود، کارش را «رهاشده» می‌گذارد و RQ آن را با همان سیاست تلاش مجدد دوباره در صف قرار می‌دهد.
  - کار ناموفق ۷ روز نگه داشته می‌شود؛ نتیجه‌ی کار موفق ۱۰ دقیقه (حافظه‌ی Broker با حجم بالا بی‌حد رشد نمی‌کند).
- **Redis** (`base/redis/redis.conf`):
  - `appendonly` + `appendfsync everysec`: بیشترین هدررفت در قطعی ناگهانی ۱ ثانیه.
  - `maxmemory 384mb` + `noeviction`: با پر شدن حافظه هیچ کاری بی‌صدا حذف نمی‌شود؛ هشدار `RedisMemoryHigh` در ۸۰٪.
  - lazyfree، `tcp-keepalive` و SLOWLOG.
  - کلاینت‌های برنامه: Timeout اتصال و `health_check_interval`.
- **ایندکس‌های جستجو** (مایگریشن `9c4e2a7b1d35`):
  - GIN روی آرایه‌ی حروف‌کوچک مهارت‌ها (`ats_resume_skill_keys`).
  - B-Tree روی سابقه (`ats_resume_experience_years`).
  - هر دو با `fastupdate`، و Autovacuum حساس به درج برای جدول `resumes`.
  - ایندکس GIN بلااستفاده‌ی قبلی (`jsonb_path_ops`) حذف شد.
  - همه `CONCURRENTLY`، بدون قفل نوشتن روی جدول.

---

## مانیتورینگ، هشدار و بک‌آپ

- **Prometheus** اهداف را با Kubernetes Service Discovery (فقط Pod های همین Namespace، با Role محدود) پیدا می‌کند. هر نسخه‌ی HPA بک‌اند خودکار Scrape می‌شود و برچسب `pod` دارد.
  - وضعیت خود کلاستر: **kube-state-metrics** (Pod ها، Deployment ها، HPA، Node ها) و **cAdvisor** داخل kubelet (CPU/RAM هر کانتینر، از مسیر Proxy سرور API با ClusterRole فقط‌خواندنی `nodes/proxy`).
  - داشبورد **«ATS Smart — کلاستر Kubernetes»** (به‌روزرسانی هر ۱۰ ثانیه، فیلتر Pod): وضعیت کلی کلاستر، CPU/RAM/Throttling هر Pod، نسخه‌های Deployment ها و HPA ها، صف‌های Redis، و بار PostgreSQL و Ingress.
- **Alertmanager** هشدارها را به `http://backend-api:8000/api/v1/ops/alerts` می‌فرستد و این‌ها به اعلان‌های داخل سایت تیم فنی تبدیل می‌شوند. توکن از Secret به‌صورت فایل Mount می‌شود.
- **backup:**
  - همان ایمیج و زمان‌بندی Compose (کامل ۰۲:۰۰، WAL ساعتی، رزومه‌ها جمعه‌ها).
  - PVC آرشیو WAL را با پستگرس به اشتراک دارد. چون این PVC از نوع ReadWriteOnce است، `podAffinity` بک‌آپ را روی همان Node پستگرس قرار می‌دهد.
  - Sidecar textfile متریک‌های `ats_backup_*` را برای هشدارهای گروه backup می‌فرستد.
- **تمرین بازیابی فاجعه** (بازیابی کامل از Offsite در یک نمونه‌ی جدید داخل یک Job موقت):

```bash
kubectl -n ats-smart create secret generic backup-restore-key --from-file=age-identity.txt=backup/secrets/private/age-identity.txt
kubectl -n ats-smart create job backup-drill-$(date +%s) --from=cronjob/backup-drill
kubectl -n ats-smart logs -f job/<نام Job>
kubectl -n ats-smart delete secret backup-restore-key            # کلید خصوصی بعد از تمرین روی کلاستر نماند
```

---

## انتقال به کلاستر واقعی (Production)

یک Overlay جدید (مثلاً `k8s/overlays/production`) با `resources: [../../base]` بسازید و فقط این‌ها را تغییر دهید:

| موضوع | لوکال | Production |
|---|---|---|
| StorageClass | `docker.io/hostpath` + Retain | CSI ابر (`ebs.csi.aws.com`، `pd.csi.storage.gke.io`، Cinder ابر آروان و ...) + Retain |
| رزومه‌ها (`media`، RWX) | hostpath | NFS / EFS / CephFS، یا بهتر `STORAGE_BACKEND=s3` |
| ایمیج‌ها | Image Store محلی | `images: newName: <DOCKERHUB_USERNAME>/ats-smart-backend` + تگ `sha-…` CI |
| دسترسی بیرونی | NGINX Ingress روی localhost:8081 | همان Ingress Controller روی 80/443 (`k8s/addons/nginx-ingress`) + TLS (cert-manager)؛ دامنه‌ی واقعی در Ingress و `FRONTEND_ORIGIN=https://<دامنه>` |
| Secret ها | فایل‌های `secrets/*.env` | Sealed Secrets / External Secrets (Vault، AWS Secrets Manager) |
| Offsite بک‌آپ | PVC `offsite` | باکت S3 جدا (پیش‌فرض `base/backup/backup.env`) |
| metrics-server | `k8s/addons` | معمولاً از پیش روی کلاسترهای مدیریت‌شده نصب است |

---

## دستورهای پرکاربرد

```bash
kubectl -n ats-smart get pods,svc,pvc,hpa                 # نمای کلی
kubectl get pv                                            # Persistent Volume ها و reclaimPolicy
kubectl -n ats-smart logs -f deploy/backend-api           # لاگ (همه‌ی نسخه‌ها: -l app.kubernetes.io/name=backend-api)
kubectl -n ats-smart rollout restart deploy/backend-api   # ری‌استارت بدون قطعی
kubectl -n ats-smart rollout undo deploy/backend-api      # بازگشت به نسخه‌ی قبلی
kubectl -n ats-smart exec deploy/redis -c redis -- redis-cli INFO memory   # حافظه‌ی Broker (maxmemory/noeviction)
kubectl -n ats-smart exec -it postgres-0 -c postgres -- psql -U ats smart_ats_db
kubectl delete namespace ats-smart                        # حذف کامل (PV ها با Retain باقی می‌مانند)
```

## محدودیت‌های شناخته‌شده

- **پستگرس تک‌نسخه‌ای است.** دسترس‌پذیری بالای لایه‌ی برنامه با چند نسخه و HPA تأمین شده است، اما برای Failover خودکار دیتابیس، یک Operator مثل CloudNativePG یا Zalando (Primary + Replica) یا دیتابیس مدیریت‌شده‌ی ابری پیشنهاد می‌شود. همین برای Redis هم صادق است (Sentinel، یا سرویس مدیریت‌شده).
- **PVC `media` به ReadWriteMany نیاز دارد.** روی کلاستر چند Node باید از StorageClass با پشتیبانی RWX یا ذخیره‌سازی S3 استفاده شود.
- **ایمیل‌های محیط لوکال به Mailpit می‌روند** (http://localhost:8025)، نه به بیرون. برای ارسال واقعی، `SMTP_*` را در `overlays/local/config.env` و `secrets/backend.env` تنظیم کنید.
- **cAdvisor روی Docker Desktop برچسب pod ندارد** (cri-dockerd)؛ مصرف هر Pod از مسیر cgroup و پیوند UID با kube-state-metrics به دست می‌آید (`base/monitoring/recording-rules.yml`). شبکه‌ی جدای هر Pod آنجا گزارش نمی‌شود؛ روی کلاسترهای containerd همه‌چیز مستقیم در دسترس است.
- **مقیاس Worker ها بر اساس CPU/RAM است، نه طول صف.** برای مقیاس بر اساس تعداد کارهای منتظر (و حتی صفر کردن Worker ها در زمان بیکاری)، KEDA با Scaler مخصوص Redis پیشنهاد می‌شود.
- **ایمیج‌های `registry.k8s.io` از ایران در دسترس نیستند** (پاسخ 403). برای افزونه‌ها از آینه‌های Docker Hub استفاده شده است (`rancher/mirrored-*`).
