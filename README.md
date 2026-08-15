# ATS Smart

پلتفرم هوشمند جذب و استخدام و تحلیل رزومه. این ریپو شامل دو بخش است:
- ریشه‌ی ریپو (`app/`, `alembic/`, ...): بک‌اند (FastAPI + Async)
- پوشه‌ی `frontend/`: فرانت‌اند (React + TypeScript + Tailwind CSS)

راهنمای هرکدام در فایل README مخصوص همان بخش آمده:
- راهنمای بک‌اند: همین فایل (پایین‌تر)
- راهنمای فرانت‌اند: `frontend/README.md`

---

## بک‌اند — راه‌اندازی محیط توسعه

```bash
python -m venv .venv
source .venv/bin/activate      # ویندوز: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# سپس مقادیر واقعی DATABASE_URL، REDIS_URL و SECRET_KEY را در .env تنظیم کنید
```

## اجرای سرور

```bash
uvicorn app.main:app --reload
```

- Swagger: http://127.0.0.1:8000/docs
- بررسی سلامت سرور: http://127.0.0.1:8000/api/v1/health

## اجرای تست‌ها

```bash
pytest
```

## مدیریت پایگاه داده با Alembic

اعمال آخرین ساختار جداول روی دیتابیس محلی:
```bash
alembic upgrade head
```

ساخت یک فایل migration جدید بعد از تغییر مدل‌ها:
```bash
alembic revision --autogenerate -m "توضیح کوتاه تغییر"
```

## احراز هویت (Auth)

### ثبت‌نام کاربر جدید
```
POST /api/v1/auth/register
```
عمومی (بدون نیاز به ورود قبلی). بدنه‌ی درخواست:
```json
{
  "email": "user@example.com",
  "password": "حداقل 8 کاراکتر",
  "role": "Candidate"
}
```
مقادیر مجاز `role`: `Admin`, `HR_Manager`, `Interviewer`, `Candidate`

- در صورت موفقیت: کد `201` و اطلاعات کاربر ساخته‌شده (بدون پسورد)
- در صورت تکراری بودن ایمیل: کد `400`
- گذرواژه هرگز خام ذخیره نمی‌شود؛ همیشه با Bcrypt هش می‌شود (ستون `password_hash` در جدول `users`)

### ورود کاربر
```
POST /api/v1/auth/login
```
عمومی. بدنه‌ی درخواست:
```json
{
  "email": "user@example.com",
  "password": "همان پسورد ثبت‌نام"
}
```

- در صورت موفقیت: کد `200` و بدنه‌ی پاسخ شامل `access_token`, `refresh_token`, `token_type`, `expires_in`
- در صورت ایمیل یا پسورد اشتباه: کد `401`
- `access_token`: طول عمر کوتاه (پیش‌فرض ۱۵ دقیقه)، برای امضای درخواست‌های بعدی فرانت‌اند
- `refresh_token`: طول عمر بلند (پیش‌فرض ۷ روز)، هم در بدنه‌ی پاسخ و هم در یک کوکی `HttpOnly` + `Secure` + `SameSite=Strict` قرار می‌گیرد

⚠️ نکته: چون کوکی با پرچم `Secure` تنظیم شده، مرورگر فقط آن را روی یک "Secure Context" ذخیره می‌کند. آدرس `http://localhost:8000/docs` این شرط را دارد، ولی `http://127.0.0.1:8000/docs` **ندارد**.

## کنترل دسترسی بر اساس نقش (RBAC)

مسیرهای حساس با `Depends(require_roles(...))` محافظت می‌شوند:
- بدون توکن یا با توکن نامعتبر/منقضی → کد `401`
- با توکن معتبر ولی نقش غیرمجاز → کد `403`

نمونه‌ی محافظت‌شده: `GET /api/v1/admin/stats` (فقط `Admin`). برای فراخوانی هر مسیر محافظت‌شده در Swagger، روی دکمه‌ی 🔒 **Authorize** بالای صفحه بزنید و `access_token` را وارد کنید (بدون کلمه‌ی `Bearer`).

## پروتکل‌های امنیتی شبکه

- **CORS**: فقط دامنه‌ی `FRONTEND_ORIGIN` (پیش‌فرض `http://localhost:5173`) اجازه‌ی دسترسی دارد.
- **Rate Limiting**: مسیرهای `register` و `login` هرکدام حداکثر ۵ درخواست در دقیقه به ازای هر آی‌پی؛ بیشتر از آن → `429`.
- **SameSite=Strict**: روی کوکی `refresh_token` تنظیم شده (دفاع CSRF).
- **Sanitize (XSS)**: ورودی‌های متنی پیش از پردازش از تگ HTML پاک می‌شوند (`app/core/sanitize.py`).

## مدیریت آگهی‌های شغلی (Job Service)

### ساخت آگهی جدید
```
POST /api/v1/jobs/
```
فقط نقش‌های `Admin` و `HR_Manager` (نیاز به `Authorize` با یک access_token معتبر). بدنه‌ی درخواست:
```json
{
  "title": "Backend Python Developer",
  "department": "Engineering",
  "description": "توضیحات آگهی...",
  "skills_required": ["Python", "FastAPI", "Docker"],
  "salary_range": "40M-60M"
}
```
- موفقیت: کد `201` و خروجی شامل `job_id`, `status: "Active"`, `created_by`
- بدون توکن: کد `401`
- با نقش غیرمجاز (مثلاً `Candidate`): کد `403`

### دریافت لیست آگهی‌ها
```
GET /api/v1/jobs/
```
عمومی (بدون نیاز به توکن) — کد `200`. فیلترهای اختیاری: `?status=Active`، `?department=Engineering`

### بستن یک آگهی (Soft Delete)
```
DELETE /api/v1/jobs/{job_id}
```
فقط `Admin` و `HR_Manager`. رکورد پاک نمی‌شود؛ فقط `status` به `Closed` تغییر می‌کند.

⚠️ نکته‌ی فنی: چون هنوز مسیری برای «ساخت شرکت» در پروژه پیاده‌سازی نشده، آگهی‌ها فعلاً مستقیم به شرکت (`company_id`) وصل نیستند و به‌جایش به کاربر سازنده‌شان (`created_by`) وصل‌اند؛ این فیلد در پاسخ ساخت آگهی برگردانده می‌شود.

## ماشین وضعیت صلب فرآیند استخدام (Application Status Service)

بورد کانبان کارجویان با یک ماشین وضعیت صلب (Strict State Machine) کنترل می‌شود
تا هیچ درخواستی نتواند از روی مراحل استاندارد «پرش» کند.

### مسیر خطی مجاز
```
Draft → Applied → Screening → Technical Interview → HR Interview → Offer → Accepted → Hired
```
از هر مرحله (به‌جز حالت‌های نهایی)، همیشه یک مسیر دوم هم مجاز است: انتقال به **Rejected**
(رد شدن کارجو در هر نقطه از فرآیند). `Hired` و `Rejected` وضعیت‌های نهایی‌اند و از آن‌ها
هیچ انتقال دیگری مجاز نیست.

منطق کامل قوانین در `app/core/state_machine.py` تعریف شده است.

### دریافت لیست درخواست‌های یک آگهی (برای بورد کانبان فرانت‌اند)
```
GET /api/v1/applications/?job_id={job_id}
```
فقط نقش‌های `Admin` و `HR_Manager`. هر آیتم شامل `application_id`, `candidate_id`,
`candidate_name`, `current_status`, `score_ai`, `updated_at` است — دقیقاً همان اطلاعاتی
که برای رندر یک «کارت» روی بورد کانبان لازم است.

### جابه‌جایی وضعیت
```
PUT /api/v1/applications/{application_id}/status
```
فقط نقش‌های `Admin` و `HR_Manager` (نیاز به `Authorize` با یک access_token معتبر). بدنه‌ی درخواست:
```json
{
  "current_status": "Screening",
  "new_status": "Technical Interview"
}
```

- **موفقیت (پرش مجاز):** کد `200` و بدنه‌ی پاسخ شامل `application_id`, `previous_status`,
  `new_status`, `updated_at`. یک ردیف جدید هم در جدول `status_history` ثبت می‌شود
  (شامل `old_status`, `new_status`, `changed_by`, `changed_at`).
- **پرش غیرمجاز** (مثلاً درخواست مستقیم از `Screening` به `Hired`، یا `current_status`
  ارسالی با وضعیت واقعی رکورد در دیتابیس یکی نباشد): تراکنش کامل Rollback می‌شود و
  کد `400` با پیام دقیق `"Business Logic Violation"` برگردانده می‌شود.
- بدون توکن: کد `401`. با نقش غیرمجاز (مثلاً `Candidate` یا `Interviewer`): کد `403`.
- درخواست با `application_id` ناموجود: کد `404`.

## آپلود رزومه (Resume Upload Service)

```
POST /api/v1/resumes/upload
```
فقط نقش `Candidate`. بدنه به‌صورت `multipart/form-data`: `job_id` (شناسه‌ی آگهی) و
`file` (فایل فیزیکی رزومه — فقط PDF یا DOCX، حداکثر ۱۰ مگابایت).

فایل در فضای ذخیره‌سازی (`app/core/storage.py` — دیسک محلی برای توسعه یا هر
Object Storage سازگار با S3 برای پروداکشن، بسته به `STORAGE_BACKEND` در `.env`)
ذخیره می‌شود و آدرسش (`file_url`) در جدول `resumes` ثبت می‌گردد. هم‌زمان، در یک
تراکنش واحد، یک ردیف جدید با وضعیت پیش‌فرض `Draft` در جدول `applications` ساخته
می‌شود — این همان راهی است که یک درخواست واقعی (نه فقط دستی/seed) ساخته می‌شود.

- موفقیت: کد `202 Accepted` با `application_id`, `status: "Draft"`, `message`.
- فرمت غیرمجاز (نه PDF نه DOCX): کد `400`.
- بدون توکن: `401` — نقش غیر از `Candidate`: `403` — `job_id` ناموجود: `404`.

## کش و صف کارهای پس‌زمینه با Redis

- **کش (Cache):** لایه‌ی سبک `app/core/cache.py` روی Redis، برای داده‌هایی که در
  هر درخواست تکرار می‌شوند به کار رفته — مشخصاً نشست کاربر لاگین‌شده در
  `get_current_user` (`app/core/deps.py`) با TTL پنج دقیقه‌ای کش می‌شود تا هر
  درخواست محافظت‌شده، کاربر را دوباره از دیتابیس نخواند.
- **صف کارها (Task Queue):** `app/core/queue.py` با کتابخانه‌ی RQ (Redis Queue).
  کارهای پس‌زمینه (مثل `app/tasks/resume_processing.py`) به‌صورت ناهمگام
  (`fire-and-forget`، بدون مسدود کردن پاسخ اصلی سرور) به صف اضافه می‌شوند.
- در startup سرور یک PING به Redis زده می‌شود و نتیجه (موفق/ناموفق) در لاگ سرور
  ثبت می‌گردد؛ در دسترس نبودن Redis باعث بالا نیامدن سرور نمی‌شود (فقط کش/صف
  موقتاً غیرفعال می‌مانند).
- برای اجرای Worker که کارهای صف را واقعاً پردازش می‌کند (باید هم‌زمان با سرور،
  در یک ترمینال جدا، در حال اجرا باشد):
  ```bash
  # لینوکس / مک:
  rq worker --url redis://localhost:6379/0 default

  # ویندوز (RQ پیش‌فرض به SIGALRM نیاز دارد که در ویندوز وجود ندارد؛
  # این اسکریپت جایگزین از Timer به‌جای سیگنال یونیکسی استفاده می‌کند):
  python -m app.worker
  ```

## ساختار کلی ریپو

```
ats-smart-backend/            # ریشه‌ی ریپو
├── app/                       # بک‌اند
│   ├── routers/                # اندپوینت‌ها (health, auth, admin, jobs, applications, resumes)
│   ├── core/
│   │   ├── config.py             # تنظیمات و متغیرهای محیطی
│   │   ├── security.py            # هش کردن گذرواژه (Bcrypt) و صدور/رمزگشایی توکن‌های JWT
│   │   ├── deps.py                # لایه‌ی RBAC: get_current_user (با کش Redis) و require_roles
│   │   ├── limiter.py              # پیکربندی Rate Limiting
│   │   ├── sanitize.py             # پاکسازی ورودی متنی در برابر XSS
│   │   ├── state_machine.py        # ماشین وضعیت صلب بورد کانبان + قانون ضدپرش
│   │   ├── storage.py               # لایه‌ی انتزاعی ذخیره‌سازی فایل (دیسک محلی / S3)
│   │   ├── redis_client.py          # اتصال Async به Redis (برای کش)
│   │   ├── cache.py                  # لایه‌ی سبک Cache روی Redis
│   │   └── queue.py                   # صف کارهای پس‌زمینه با RQ (Redis Queue)
│   ├── tasks/
│   │   └── resume_processing.py       # کارهای پس‌زمینه‌ای که Worker اجرا می‌کند
│   ├── db/
│   │   └── session.py             # اتصال async به دیتابیس
│   ├── models/                  # مدل‌های ORM (SQLAlchemy) — 14 جدول طراحی دیتابیس
│   │   ├── base.py
│   │   ├── core.py               # User, Company, Candidate, Job
│   │   ├── process.py            # Application (+ updated_at), Interview, Resume, Skill
│   │   └── security.py           # Role, Permission, Notification, Log, Audit, StatusHistory
│   ├── schemas/                  # اسکیمای Pydantic (auth.py, jobs.py, applications.py, resumes.py, health.py)
│   ├── main.py                    # نقطه ورود برنامه (شامل lifespan: بررسی اتصال Redis در startup)
│   └── worker.py                   # اجرای Worker صف کارها (سازگار با ویندوز)
├── alembic/                    # مدیریت نسخه‌بندی دیتابیس
├── tests/                       # تست‌های بک‌اند
├── frontend/                    # فرانت‌اند (React + TypeScript + Tailwind)
├── requirements.txt
└── alembic.ini
```
