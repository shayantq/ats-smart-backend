# استقرار روی Kubernetes

مهاجرت کامل ATS Smart از Docker Compose به Kubernetes برای مقیاس‌دهی خودکار و دسترس‌پذیری بالا. همان ایمیج‌های Compose بدون هیچ تغییری استفاده می‌شوند. ساختار مانیفست‌ها با **Kustomize** است که داخل خودِ `kubectl` وجود دارد و ابزار اضافه‌ای لازم ندارد.

```bash
bash k8s/deploy.sh     # استقرار/به‌روزرسانی کامل (Secret ها، ایمیج‌ها، metrics-server، مانیفست‌ها، انتظار برای Rollout)
bash k8s/verify.sh     # بررسی خودکار معیارهای پذیرش — خروجی نهایی: [ACCEPTANCE PASS]
```

| آدرس (محیط لوکال) | سرویس |
|---|---|
| http://localhost:8090 | سایت (Service فرانت‌اند، نوع LoadBalancer) |
| http://localhost:3030 | Grafana — کاربر/رمز در `k8s/overlays/local/secrets/grafana.env` |
| `kubectl -n ats-smart port-forward svc/prometheus 9091:9090` ← http://localhost:9091 | Prometheus (فقط داخل کلاستر) |

پورت‌ها عمداً با Docker Compose (8080، 3000، 8088) تداخل ندارند و هر دو محیط می‌توانند هم‌زمان اجرا شوند.

---

## معماری

```
                    مرورگر ── :8090 ──► Service frontend (LoadBalancer)
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
                 frontend Pod ×2..4 (HPA)            ── /api ، /media ──►  Service backend-api (ClusterIP)
                                                                           │ (kube-proxy: پخش بار)
                                              ┌────────────────────────────┴───────────┐
                                              ▼                                        ▼
                                   backend-api Pod ×2..6 (HPA)                  worker · scheduler
                                      │            │        └─── PVC media (RWX) ───┘
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
| 2 | `worker` | Deployment `worker` | ۱ (قابل `kubectl scale`) | PVC `media` |
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
├── overlays/local/             # Docker Desktop: StorageClass با Retain، LoadBalancer، Secret ها، Offsite محلی
│   └── secrets/*.env.example   # نمونه‌ی Secret ها (فایل‌های واقعی *.env در .gitignore)
├── addons/metrics-server/      # منبع متریک HPA (آینه‌ی Docker Hub، چون registry.k8s.io از ایران 403 می‌دهد)
├── deploy.sh · verify.sh
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
  - `ats-config` (از `base/config/app.env` + `overlays/local/config.env`)
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

نام ConfigMap و Secret ها پسوند هش دارد. با تغییر هر مقدار و اجرای دوباره‌ی `deploy.sh`، Pod های مصرف‌کننده خودکار با مقدار جدید Rollout می‌شوند.

---

## مقیاس‌دهی خودکار و استقرار بدون قطعی

- **HPA** (`base/hpa.yaml`) بر اساس CPU کار می‌کند (هدف ۷۰٪ نسبت به `requests`):
  - بک‌اند: ۲ تا ۶ نسخه
  - فرانت‌اند: ۲ تا ۴ نسخه
  - افزایش فوری، کاهش با تأخیر ۵ دقیقه‌ای
  - سقف بک‌اند با ظرفیت اتصال‌های دیتابیس هماهنگ است: `(6+1) × 12 = 84 < 100`
  - Deployment ها عمداً `replicas` ندارند تا `kubectl apply` تعداد تعیین‌شده توسط HPA را برنگرداند.
  - وضعیت: `kubectl -n ats-smart get hpa` و `kubectl top pods -n ats-smart`
- **RollingUpdate** با `maxUnavailable: 0`:
  - Pod جدید تا سبز شدن `readinessProbe` ترافیک نمی‌گیرد.
  - `preStop` (۵ ثانیه) فرصت حذف Pod از Endpoint ها را می‌دهد، و uvicorn درخواست‌های در حال اجرا را تا ۳۰ ثانیه کامل می‌کند.
  - **PodDisruptionBudget** حین تخلیه‌ی Node، حداقل یک نسخه را نگه می‌دارد.
- **مایگریشن‌ها:** Job `migrate` پیش از کد جدید اجرا می‌شود. initContainer `wait-for-migrations` در API و Worker تا رسیدن دیتابیس به `head` منتظر می‌ماند.
  - مایگریشن‌ها باید Expand/Contract باشند تا نسخه‌ی قبلی کد هم در حین انتشار با دیتابیس کار کند.
- **Probe ها:** `/api/v1/health` عمداً به دیتابیس و Redis وابسته نیست. قطعی موقت آن‌ها نباید همه‌ی Pod ها را از سرویس خارج یا ری‌استارت کند. بررسی عمیق اتصال‌ها با `/api/v1/health/ready` انجام می‌شود.

---

## مانیتورینگ، هشدار و بک‌آپ

- **Prometheus** اهداف را با Kubernetes Service Discovery (فقط Pod های همین Namespace، با Role محدود) پیدا می‌کند. هر نسخه‌ی HPA بک‌اند خودکار Scrape می‌شود و برچسب `pod` دارد.
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
| دسترسی بیرونی | LoadBalancer روی localhost | Ingress Controller + TLS (cert-manager)؛ `FRONTEND_ORIGIN=https://<دامنه>` |
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
kubectl -n ats-smart scale deploy/worker --replicas=3     # Worker بیشتر برای صف شلوغ
kubectl -n ats-smart exec -it postgres-0 -c postgres -- psql -U ats smart_ats_db
kubectl delete namespace ats-smart                        # حذف کامل (PV ها با Retain باقی می‌مانند)
```

## محدودیت‌های شناخته‌شده

- **پستگرس تک‌نسخه‌ای است.** دسترس‌پذیری بالای لایه‌ی برنامه با چند نسخه و HPA تأمین شده است، اما برای Failover خودکار دیتابیس، یک Operator مثل CloudNativePG یا Zalando (Primary + Replica) یا دیتابیس مدیریت‌شده‌ی ابری پیشنهاد می‌شود. همین برای Redis هم صادق است (Sentinel، یا سرویس مدیریت‌شده).
- **PVC `media` به ReadWriteMany نیاز دارد.** روی کلاستر چند Node باید از StorageClass با پشتیبانی RWX یا ذخیره‌سازی S3 استفاده شود.
- **SMTP در محیط لوکال تنظیم نشده** (`SMTP_HOST=localhost`)، مثل محیط توسعه‌ی Compose. ثبت‌نام و تغییر وضعیت کار می‌کنند، اما کار ارسال ایمیل در Worker با `Connection refused` شکست می‌خورد. برای ایمیل واقعی، `SMTP_*` را در `overlays/local/config.env` و `secrets/backend.env` تنظیم کنید.
- **ایمیج‌های `registry.k8s.io` از ایران در دسترس نیستند** (پاسخ 403). برای افزونه‌ها از آینه‌های Docker Hub استفاده شده است (`rancher/mirrored-*`).
