# معماری Zero-Trust در ارتباطات بین سرویس‌ها

هیچ سرویسی صرفاً چون «داخل شبکه» است، مورد اعتماد نیست. دو لایه‌ی مستقل این را تضمین می‌کنند:

1. **هویت سرویس:** هر فراخوانی داخلی یک توکن JWT امضاشده‌ی نامتقارن و کوتاه‌عمر در هدر `X-Internal-Auth` دارد. بدون توکن معتبر ← `401`.
2. **تفکیک شبکه:** هر سرویس فقط به سرویس‌ها و پورت‌هایی دسترسی دارد که واقعاً لازم دارد. کانتینر یا Pod غیرمجاز حتی اتصال TCP به پایگاه داده را برقرار نمی‌کند، چون بسته‌ها در لایه‌ی شبکه دور ریخته می‌شوند.

---

## ۱. فهرست ارتباطات واقعی بین سرویس‌ها

| از ← به | مسیر | احراز هویت |
|---|---|---|
| **سرویس هوش مصنوعی (worker / genai-worker) ← API** | `GET /api/v1/internal/applications/{id}/interview-profile` | **توکن سرویس ES256 (`X-Internal-Auth`)** |
| Alertmanager ← API | `POST /api/v1/ops/alerts` | توکن ثابت `OPS_WEBHOOK_TOKEN` (Alertmanager امضای JWT ندارد) |
| Prometheus ← API و Exporter ها | `GET /metrics` | فقط تفکیک شبکه |
| genai-worker ← سرور مدل (لوکال) | `POST /v1/chat/completions` | فقط تفکیک شبکه |
| API / Worker ها ← PostgreSQL، Redis | TCP | رمز پایگاه داده + تفکیک شبکه |
| resume-worker ← فایل رزومه | دیسک مشترک (HTTP نیست) | — |

پیش از این تسک، سرویس هوش مصنوعی رزومه و آگهی را مستقیم از جدول‌ها می‌خواند. حالا پروفایل بدون اطلاعات شخصی را از سرویس رزومه/API می‌گیرد و فقط برای سازمانِ داخل توکن.

---

## ۲. توکن سرویس‌به‌سرویس (`app/core/service_auth.py`)

```
genai-worker / worker                                  backend-api
──────────────────────                                 ───────────
کلید خصوصی خودش (فایل Secret)                          فقط کلیدهای عمومی (<سرویس>.pem)
        │                                                     ▲
        │  GET /api/v1/internal/...                           │ ۱. هدر X-Forwarded-For؟ ← 404 (از اینترنت نیامده)
        │  X-Internal-Auth: <JWT ES256>                       │ ۲. alg=ES256، kid در فهرست سرویس‌های مجاز
        └────────────────────────────────────────────────────►│ ۳. امضا با کلید عمومی همان سرویس
                                                              │ ۴. aud=backend-api، exp/iat، عمر ≤ ۵ دقیقه، jti، typ=service
                                                              │ ۵. tid ← Context سازمان (RLS) — فقط داده‌ی همان سازمان
```

| فیلد | مقدار |
|---|---|
| الگوریتم | **ES256** (ECDSA P-256). نامتقارن است: لو رفتن کلید یک سرویس امکان جعل هویت سرویس دیگری را نمی‌دهد. کتابخانه‌ی موجود (python-jose + cryptography) EdDSA ندارد؛ ES256 نسبت به RS256 کلید و امضای کوچک‌تر و سریع‌تری دارد. |
| Header | `kid` = نام سرویس فرستنده |
| Claims | `iss`/`sub` فرستنده · `aud` گیرنده · `iat`/`nbf`/`exp` (پیش‌فرض ۶۰ ثانیه، سقف ۳۰۰) · `jti` یکتا · `typ=service` · `tid` سازمان (اختیاری) |
| رد می‌شود (`401`) | نبود هدر · منقضی · audience دیگر · امضای کلید ناشناخته · سرویس خارج از فهرست مجاز · دست‌کاری Payload · Algorithm Confusion (HS256 با کلید عمومی) · عمر بیش از سقف · توکن کاربر |
| حداقل دسترسی | توکن بدون `tid` ← `403`. توکن سازمان دیگر ← `404` (RLS). |

### مدیریت کلید

| محیط | کلید خصوصی (فقط سرویس فرستنده) | کلید عمومی (API) | ساخت |
|---|---|---|---|
| سرور (Docker Compose) | `secrets/service-auth/worker.key` ← **Compose secret** `/run/secrets/worker_service_key` | `secrets/service-auth/public/` ← `/run/service-auth/public` (فقط خواندنی) | `deploy/deploy.sh` یک‌بار روی خود سرور با openssl |
| Kubernetes | Secret `ats-service-auth-genai-worker` ← Volume فایل `0440` | Secret `ats-service-auth-public` ← Volume فایل | `k8s/deploy.sh` ← secretGenerator |

- کلیدها هرگز در ریپو (`.gitignore`)، `.env`، ConfigMap، متغیر محیطی یا خروجی CI نیستند.
- پوشه‌ی `secrets` روی سرور فقط برای کاربر استقرار باز است (`700`).
- **چرخش کلید:** فایل‌های کلید را پاک کنید و دوباره مستقر کنید. جفت‌کلید جدید ساخته می‌شود و API و Worker با هم ری‌استارت می‌شوند. توکن‌های قدیمی حداکثر چند ثانیه پس از آن منقضی‌اند.

---

## ۳. تفکیک شبکه

### سرور Production (Docker Compose)

| شبکه | اعضا | نوع |
|---|---|---|
| `ats_network` (وب) | gateway، frontend، backend_api، grafana | عادی |
| `ats_data` | **postgres_db**، backend_api، worker، migrate، backup، postgres_exporter | `internal` (بدون اینترنت) |
| `ats_cache` | **redis_cache**، backend_api، worker، scheduler، redis_exporter | `internal` |
| `ats_internal` | backend_api، worker (مسیر S2S امضاشده) | `internal` |
| `ats_monitoring` | prometheus، alertmanager، grafana، exporter ها، backend_api | عادی |
| `ats_egress` | worker (SMTP، سرویس مدل بیرونی) | عادی |

Docker بسته‌های بین شبکه‌های جدا را دور می‌ریزد. کانتینری که عضو `ats_data` نیست (فرانت‌اند، Gateway، یا هر کانتینر ناشناس) **حتی نام `postgres_db` را Resolve نمی‌کند** و اتصال TCP مستقیم به IP آن بی‌پاسخ می‌ماند.

### Kubernetes (`k8s/base/network-policies.yaml`)

`default-deny-all` (Ingress و Egress) + `allow-dns`، سپس برای هر سرویس فقط موارد زیر:

| سرویس | ورودی مجاز | خروجی مجاز |
|---|---|---|
| postgres | 5432 از backend-api، worker، resume-worker، genai-worker، migrate، backup · 9187 از prometheus | — |
| redis | 6379 از backend-api، worker ها، scheduler · 9121 از prometheus | — |
| backend-api | 8000 از nginx-ingress، frontend، alertmanager، prometheus، genai-worker | postgres، redis، HTTPS اینترنت (S3) |
| frontend | 80 از nginx-ingress | backend-api:8000 |
| genai-worker | — | backend-api:8000، genai-inference:8080، postgres، redis، HTTPS اینترنت |
| worker | — | postgres، redis، mailpit:1025، SMTP اینترنت |
| resume-worker | — | postgres، redis، HTTPS اینترنت |
| scheduler | — | redis |
| migrate | — | postgres |
| backup | 9100 از prometheus | postgres، HTTPS/SFTP اینترنت (Offsite) |
| prometheus | 9090 از grafana | آزاد (کشف و جمع‌آوری متریک) |
| alertmanager | 9093 از prometheus | backend-api:8000 |
| grafana | 3000 (LoadBalancer) | prometheus:9090 |
| genai-inference · mailpit | 8080 فقط از genai-worker · 1025 فقط از worker ها | HTTPS (دانلود مدل) · — |

---

## ۴. راستی‌آزمایی

```bash
pytest tests/unit/test_service_auth.py tests/integration/test_internal_api.py
cd /opt/ats-smart && bash deploy/zero-trust-check.sh        # روی سرور ← [ZERO TRUST PASS]
```

| سناریو | انتظار |
|---|---|
| از داخل کانتینر Worker: بدون هدر / منقضی / audience اشتباه / کلید ناشناخته | `401` |
| توکن معتبر Worker | `200` |
| همان مسیر از اینترنت (دامنه‌ی عمومی)، حتی با توکن معتبر | `404` |
| کانتینر ناشناس روی شبکه‌ی وب ← PostgreSQL:5432 و Redis:6379 | بی‌پاسخ (Timeout)؛ نام هم Resolve نمی‌شود |
| API ← PostgreSQL و Redis | اتصال برقرار |

---

## ۵. محدودیت‌ها و تصمیم‌ها

- **mTLS:** Service Mesh (Linkerd حدود ۳۵۰ تا ۵۰۰ مگ، Istio بیشتر) با رم سرور (۴ گیگ، مشترک با LogiTrack) جور نیست. Production هم Kubernetes نیست. به‌جایش احراز هویت متقابل در لایه‌ی برنامه با توکن امضاشده‌ی نامتقارن و تفکیک شبکه انجام شده است. ترافیک داخل یک میزبان از شبکه‌ی عمومی عبور نمی‌کند. قدم بعدی در صورت مهاجرت Production به Kubernetes: Linkerd (mTLS خودکار و چرخش گواهی).
- **اجرای NetworkPolicy:** شبکه‌ی پیش‌فرض Docker Desktop (`vpnkit`) NetworkPolicy را می‌پذیرد ولی اعمال نمی‌کند. آزمون: پس از `deny-all` اتصال همچنان برقرار بود. پالیسی‌ها برای کلاستر دارای Calico یا Cilium آماده‌اند. اثبات قطع TCP روی سرور واقعی با تفکیک شبکه‌ی Docker انجام شده است.
- **Replay:** توکن‌ها `jti` دارند ولی فهرست `jti` مصرف‌شده نگه داشته نمی‌شود. عمر کوتاه (۶۰ ثانیه)، محدودیت audience و سازمان، و تفکیک شبکه ریسک را محدود می‌کنند.
- **Alertmanager و Prometheus** امضای JWT پشتیبانی نمی‌کنند. برای آن‌ها توکن ثابت (ops) و تفکیک شبکه استفاده شده است.
