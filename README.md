# ATS Smart

پلتفرم هوشمند جذب و استخدام و تحلیل رزومه.

- **بک‌اند** (ریشه‌ی ریپو): FastAPI (Async) · PostgreSQL · SQLAlchemy 2 · Alembic · Redis (کش + صف RQ)
- **فرانت‌اند** (`frontend/`): React · TypeScript · Vite · Tailwind — راهنمای جدا: [`frontend/README.md`](frontend/README.md)
- **زیرساخت:** Docker (Multi-stage) · Docker Compose · GitHub Actions · Prometheus · Grafana · Alertmanager

**امکانات اصلی:** احراز هویت JWT و RBAC · مدیریت آگهی · بورد کانبان با ماشین وضعیت صلب · آپلود رزومه و خط لوله‌ی هوش مصنوعی (OCR → NER → موتور مهارت → نمره‌ی تطابق) · پورتال کارجو · مدیریت مصاحبه با یادآور خودکار · اطلاع‌رسانی ایمیلی · جستجوی پیشرفته‌ی کارجویان · داشبورد تحلیلی · مانیتورینگ و هشدار زنده

## فهرست

- [راه‌اندازی سریع با Docker](#راهاندازی-سریع-با-docker)
- [توسعه‌ی محلی بدون Docker](#توسعهی-محلی-بدون-docker)
- [تست و کیفیت کد](#تست-و-کیفیت-کد)
- [متغیرهای محیطی](#متغیرهای-محیطی)
- [API و امکانات](#api-و-امکانات)
- [خط لوله‌ی هوش مصنوعی رزومه](#خط-لولهی-هوش-مصنوعی-رزومه)
- [زیرساخت: Docker، مانیتورینگ، CI/CD و استقرار](#زیرساخت-docker-مانیتورینگ-cicd-و-استقرار)
- [ساختار ریپو](#ساختار-ریپو)
- [محدودیت‌های شناخته‌شده](#محدودیتهای-شناختهشده)

---

## راه‌اندازی سریع با Docker

کل سیستم (بک‌اند، فرانت‌اند، دیتابیس، Redis، Worker و مانیتورینگ) با یک دستور — بدون نصب PostgreSQL/Redis/Tesseract روی سیستم:

```bash
cp .env.example .env          # برای اجرای لوکال، مقادیر پیش‌فرض کافی‌اند
docker compose up -d --build
docker compose ps             # همه Up؛ فقط migrate بعد از اجرای مایگریشن‌ها Exited (0) است
```

| آدرس | سرویس |
|---|---|
| http://localhost:8080 | سایت (فرانت‌اند) |
| http://localhost:8000/docs | Swagger بک‌اند |
| http://localhost:3000 | Grafana (لوکال: `admin` / `admin`) |
| http://localhost:9090 · http://localhost:9093 | Prometheus · Alertmanager |

- `docker compose down` داده‌ها را **پاک نمی‌کند** (Volumeهای نام‌دار)؛ فقط `docker compose down -v` همه‌چیز را حذف می‌کند.
- اگر دانلود بسته‌های Debian حین بیلد وسط کار قطع شد (`unexpected EOF`): `docker compose build --build-arg DEBIAN_MIRROR=https://deb.debian.org`

---

## توسعه‌ی محلی بدون Docker

پیش‌نیازها: Python 3.11+، PostgreSQL، Redis، و **موتور Tesseract OCR** (یک نرم‌افزار سیستمی جدا از pip، به‌همراه داده‌ی زبان فارسی).

```bash
python -m venv .venv
source .venv/bin/activate              # ویندوز: .venv\Scripts\activate
pip install -r requirements-dev.txt    # وابستگی‌های برنامه + ابزارهای تست و Lint
python -m spacy download en_core_web_sm  # مدل NER (بدون آن هم کار می‌کند، فقط با دقت کمتر)

cp .env.example .env                   # DATABASE_URL، REDIS_URL و SECRET_KEY را تنظیم کنید
alembic upgrade head                   # ساخت/به‌روزرسانی جداول
uvicorn app.main:app --reload          # http://localhost:8000/docs
```

پردازش‌های پس‌زمینه هرکدام در یک ترمینال جدا:

```bash
python -m app.worker                            # Worker صف (پردازش رزومه، ایمیل) — سازگار با ویندوز
rqscheduler --host localhost --port 6379        # زمان‌بند یادآورهای مصاحبه
```

- ساخت migration جدید بعد از تغییر مدل‌ها: `alembic revision --autogenerate -m "توضیح"`
- اگر Tesseract در PATH نیست (مخصوصاً ویندوز)، مسیر کامل `tesseract.exe` را در `TESSERACT_CMD_PATH` بدهید.
- روی لینوکس/مک به‌جای `python -m app.worker` می‌توان از `rq worker --url redis://localhost:6379/0 default` هم استفاده کرد (Worker پیش‌فرض RQ به `SIGALRM` نیاز دارد که در ویندوز وجود ندارد).

---

## تست و کیفیت کد

```bash
pytest                    # همه‌ی تست‌ها (واحد + یکپارچه‌سازی)
pytest -m unit            # فقط تست‌های واحد — بدون هیچ وابستگی بیرونی
pytest -m integration     # فقط تست‌های یکپارچه‌سازی — نیازمند PostgreSQL
pytest --cov              # همراه با گزارش پوشش کد
black app tests && flake8 # فرمت و استانداردهای نگارش (تنظیمات: pyproject.toml و .flake8)
```

| لایه | مسیر | چه چیزی را می‌سنجد |
|---|---|---|
| **واحد** | `tests/unit/` | توابع ایزوله: موتور نمره‌دهی، سن کارجو (`ValueError` برای سن منفی)، ماشین وضعیت، پارسر جستجو، گراف مهارت و تحلیل سابقه، پارسر رزومه، امنیت (Bcrypt/JWT/XSS)، صفحه‌بندی |
| **یکپارچه‌سازی** | `tests/integration/` | درخواست HTTP واقعی (HTTPX AsyncClient) به API و بررسی مستقیم جداول: آگهی‌ها، احراز هویت و بازیابی رمز، کانبان و قیف تحلیلی، پورتال کارجو، آپلود رزومه، جستجوی متنی، مصاحبه‌ها، اعلان‌ها، متریک‌ها |

**دیتابیس تست موقت و جدا** (`tests/integration/conftest.py`): در شروع، یک دیتابیس جدید با نام یکتا (مثلاً `smart_ats_db_test_1a2b3c4d`) روی همان سرور `DATABASE_URL` (یا `TEST_DATABASE_URL`) ساخته و کل مایگریشن‌های واقعی روی آن اجرا می‌شود — دیتابیس اصلی توسعه هرگز دست نمی‌خورد. هر تست داخل یک تراکنش اجرا می‌شود که در پایانش Rollback می‌شود (هر تست با جداول خالی شروع می‌شود) و در پایان کل دیتابیس موقت حذف می‌شود. Redis، ایمیل و صف در این تست‌ها با جایگزین‌های حافظه‌ای عوض می‌شوند. اگر PostgreSQL در دسترس نباشد این تست‌ها Skip می‌شوند — مگر با `TEST_DB_REQUIRED=1` (مثل CI) که Fail می‌شوند.

همین بررسی‌ها (به‌علاوه‌ی گزارش پوشش کد) در خط لوله‌ی CI اجرا می‌شوند.

---

## متغیرهای محیطی

نمونه‌ی کامل در [`.env.example`](.env.example). مقادیر حساس هرگز داخل کد نوشته نمی‌شوند.

| متغیر | توضیح |
|---|---|
| `DATABASE_URL` · `REDIS_URL` | اتصال PostgreSQL (asyncpg) و Redis — داخل Docker خودکار با نام سرویس‌ها ساخته می‌شوند |
| `SECRET_KEY` | کلید امضای JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` · `REFRESH_TOKEN_EXPIRE_DAYS` | عمر توکن‌ها (پیش‌فرض ۱۵ دقیقه / ۷ روز) |
| `FRONTEND_ORIGIN` | تنها Origin مجاز CORS |
| `STORAGE_BACKEND` | `local` (دیسک، پیش‌فرض) یا `s3` (AWS S3، Liara، ArvanCloud، MinIO و ...) |
| `MEDIA_ROOT` · `MEDIA_BASE_URL` | مسیر و آدرس فایل‌های آپلودی در حالت `local` |
| `S3_*` | فقط برای `STORAGE_BACKEND=s3` |
| `OCR_LANGUAGES` · `TESSERACT_CMD_PATH` | زبان‌های OCR (پیش‌فرض `fas+eng`) و مسیر باینری Tesseract |
| `SMTP_*` | سرویس ایمیل (برای تست بدون ایمیل واقعی: Mailtrap یا یک SMTP Debug Server محلی) |
| `OPS_WEBHOOK_TOKEN` | توکن مشترک Alertmanager و CI برای `/api/v1/ops/*` — خالی = غیرفعال |
| `OPS_ALERT_RECIPIENT_ROLES` | نقش‌های «تیم فنی» که هشدارها را می‌گیرند (پیش‌فرض `Admin`) |
| `POSTGRES_*` · `PUBLIC_BASE_URL` · `GRAFANA_ADMIN_*` · `GATEWAY_HTTP_PORT` | فقط Docker Compose / سرور |

---

## API و امکانات

همه‌ی مسیرها زیر `/api/v1` هستند. در Swagger برای مسیرهای محافظت‌شده روی 🔒 **Authorize** بزنید و `access_token` را (بدون کلمه‌ی `Bearer`) وارد کنید. همه‌ی لیست‌ها **صفحه‌بندی مبتنی بر نشانگر** دارند (پارامترهای `cursor`، `direction=next|prev`، `limit` تا ۱۰۰؛ پاسخ شامل `next_cursor`/`previous_cursor`/`has_next`/`has_previous`، بدون `total`).

### احراز هویت و امنیت

| مسیر | دسترسی | توضیح |
|---|---|---|
| `POST /auth/register` | عمومی | `{email, password (حداقل ۸), role}` — نقش‌ها: `Admin`, `HR_Manager`, `Interviewer`, `Candidate` · ایمیل تکراری → `400` |
| `POST /auth/login` | عمومی | خروجی: `access_token` (۱۵ دقیقه)، `refresh_token` (۷ روز؛ هم در بدنه هم کوکی `HttpOnly`+`Secure`+`SameSite=Strict`) · اشتباه → `401` |
| `POST /auth/forgot-password` | عمومی | ارسال کد OTP شش‌رقمی به ایمیل (پاسخ همیشه یکسان، ضد User Enumeration) |
| `POST /auth/reset-password` | عمومی | `{email, otp_code, new_password}` — OTP ده دقیقه‌ای و یک‌بارمصرف |
| `GET /admin/stats` | `Admin` | آمار کلان پلتفرم (نمونه‌ی RBAC) |

- **RBAC:** با `Depends(require_roles(...))` — بدون توکن/نامعتبر `401`، نقش غیرمجاز `403`. نشست کاربر ۵ دقیقه در Redis کش می‌شود.
- **امنیت شبکه:** CORS فقط برای `FRONTEND_ORIGIN` · Rate Limit پنج درخواست در دقیقه برای هر IP روی مسیرهای auth (`429`) · پاکسازی تگ‌های HTML از ورودی‌ها (`app/core/sanitize.py`) · گذرواژه فقط به‌صورت هش Bcrypt.
- کوکی `Secure` فقط روی Secure Context ذخیره می‌شود: `http://localhost:8000/docs` بله، `http://127.0.0.1:8000/docs` **خیر**.

### آگهی‌های شغلی

| مسیر | دسترسی | توضیح |
|---|---|---|
| `POST /jobs/` | `Admin`, `HR_Manager` | `{title, department, description, skills_required[], salary_range, required_seniority, required_education, location}` → `201` با `status: Active` و `created_by` |
| `GET /jobs/` | عمومی | فیلتر اختیاری `status` و `department` |
| `DELETE /jobs/{id}` | `Admin`, `HR_Manager` | حذف منطقی: فقط `status` → `Closed` |

### بورد کانبان و ماشین وضعیت صلب

```
Draft → Applied → Screening → Technical Interview → HR Interview → Offer → Accepted → Hired
                    (از هر مرحله‌ی غیرنهایی: → Rejected)
```

| مسیر | دسترسی | توضیح |
|---|---|---|
| `GET /applications/?job_id=` | `Admin`, `HR_Manager` | کارت‌های بورد: نام کارجو، `score_ai`، وضعیت فعلی |
| `PUT /applications/{id}/status` | `Admin`, `HR_Manager` | `{current_status, new_status}` — فقط حرکت به مرحله‌ی **بلافصل** بعدی یا `Rejected` |

- هر پرش غیرمجاز (مثلاً `Screening → Hired`) یا ناهمخوانی `current_status` با دیتابیس: Rollback و `400 "Business Logic Violation"`. `Hired`/`Rejected` نهایی‌اند.
- هر جابه‌جایی موفق یک ردیف در `status_history` ثبت می‌کند و در صورت نیاز ایمیل وضعیت را به صف می‌فرستد ([ماتریس محرک‌ها](#اطلاعرسانی-ایمیلی)). منطق کامل: `app/core/state_machine.py`.

### آپلود رزومه

`POST /resumes/upload` — فقط `Candidate` · `multipart/form-data` با `job_id` و `file` (فقط PDF/DOCX، حداکثر ۱۰ مگابایت).
فایل در فضای ذخیره‌سازی (`app/core/storage.py`) ذخیره و در یک تراکنش واحد، ردیف `resumes` و یک `application` با وضعیت `Draft` ساخته می‌شود → `202 Accepted`. سپس پردازش هوش مصنوعی رزومه به صف اضافه می‌شود ([خط لوله](#خط-لولهی-هوش-مصنوعی-رزومه)). فرمت غیرمجاز `400` · آگهی ناموجود `404`.

### پورتال کارجو

همه فقط `Candidate` و همیشه روی داده‌های **خودِ** کاربر لاگین‌شده (candidate_id هرگز از ورودی گرفته نمی‌شود):

| مسیر | توضیح |
|---|---|
| `GET` / `PUT /candidates/me` | مشاهده/ویرایش پروفایل (Partial Update): نام، تلفن، `location`، تگ‌های مهارتی |
| `GET /candidates/me/applications` | رهگیر وضعیت: آگهی + مرحله‌ی فعلی هر درخواست |
| `GET /candidates/me/offers` | صندوق پیشنهادها (درخواست‌های با وضعیت `Offer`) |
| `PUT /candidates/me/applications/{id}/respond` | `{"decision": "accept" \| "reject"}` → `Accepted`/`Rejected` (از همان ماشین وضعیت) |

اولین دسترسی یک Candidate بدون پروفایل، یک پروفایل حداقلی برایش می‌سازد (`app/core/candidate_utils.py`).

### جستجوی پیشرفته‌ی کارجویان

`GET /candidates/search/?q=&skills=&skills=&min_experience_years=&min_ai_score=` — فقط `Admin`, `HR_Manager` · همه‌ی فیلترها اختیاری و با هم **AND** می‌شوند:

- **`q`:** جستجوی تمام‌متن رزومه‌ها (ایندکس GIN، Case-Insensitive، فارسی/انگلیسی) با عملگرهای `AND`/`OR` — مثلاً `Python AND Django` یا `React OR Vue`؛ بین دو کلمه‌ی بدون عملگر، AND پیش‌فرض است. «Node.js» و «C++» درست جستجو می‌شوند.
- **`skills`** (تکرارشونده): کارجو باید **همه‌ی** این مهارت‌ها را طبق موتور مهارت داشته باشد.
- **`min_experience_years`:** حداقل سابقه‌ی خالص · **`min_ai_score`:** حداقل `score_ai` (۰ تا ۱۰۰؛ خارج از بازه → `422`).
- هر ردیف شامل پروفایل خلاصه + `best_ai_score` و `best_experience_years`.

<details>
<summary>جزئیات فنی جستجو</summary>

- پارسر AND/OR دستی است (`app/core/search_query.py`) چون `websearch_to_tsquery` پستگرس کلمه‌ی `and` را عملگر نمی‌شناسد.
- پیش از `to_tsvector('simple', ...)` نویسه‌های `./+#@_-` به فاصله تبدیل می‌شوند (`resume_fts_tsvector_expression`)؛ وگرنه پارسر پستگرس «Node.js» را یک توکن واحد می‌دید. ایندکس فعلی: `ix_resumes_raw_text_fts_v2` (مایگریشن `f7b1e9a3c852`).
- ایندکس‌های پشتیبان: GIN با `jsonb_path_ops` روی `resumes.skill_analysis` و ایندکس مرکب `(candidate_id, score_ai)` روی `applications` (مایگریشن `a4d8f0c2b716`).
- `min_ai_score` یعنی «کارجویی که *حداقل در یکی* از درخواست‌هایش این نمره را گرفته» (نمره‌ی عمومیِ مستقل از آگهی وجود ندارد).
- چون `candidates` ستون زمانی ندارد، صفحه‌بندی این مسیر روی `Candidate.id` است (پایدار، ولی بدون معنای زمانی).

</details>

### مصاحبه‌ها

| مسیر | دسترسی | توضیح |
|---|---|---|
| `POST /interviews/` | `Admin`, `HR_Manager` | ساخت جلسه: `application_id`, `interviewer_id`, `scheduled_at`, `meeting_link` → `201` |
| `GET /interviews/?application_id=&date=&status=` | مدیران + `Interviewer` | لیست (Interviewer فقط مصاحبه‌های خودش) · `date=YYYY-MM-DD` · `status=Pending\|Completed` |
| `GET /interviews/{id}` | مدیران + مصاحبه‌کننده‌ی همان جلسه | جزئیات |
| `PUT /interviews/{id}` | `Admin`, `HR_Manager` | تغییر زمان/مصاحبه‌کننده/لینک (یادآورها دوباره زمان‌بندی می‌شوند) |
| `PUT /interviews/{id}/evaluation` | مصاحبه‌کننده‌ی همان جلسه یا مدیران | `{evaluation_scores, feedback_text}` → `status: Completed` |
| `DELETE /interviews/{id}` | `Admin`, `HR_Manager` | لغو + حذف یادآورها |

- `interviewer_id` باید نقش `Interviewer` یا `HR_Manager` داشته باشد، وگرنه `422`.
- معیارهای مجاز نمره (۱ تا ۱۰): `technical_skill`, `problem_solving`, `communication`, `culture_fit`. `overall_score` را سرور (میانگین) حساب می‌کند.
- **یادآور ۲۴ ساعته:** برای کارجو و مصاحبه‌کننده دقیقاً ۲۴ ساعت پیش از جلسه با **rq-scheduler** (اگر کمتر از ۲۴ ساعت مانده باشد، فوراً). شناسه‌ها در `interviews.reminder_job_ids` نگه‌داری می‌شوند تا با تغییر/لغو، یادآور قبلی cancel شود. نیازمند فرآیند `rqscheduler` در حال اجرا.

### داشبورد تحلیلی

فقط `Admin`, `HR_Manager` (بقیه `403`) · بدون کش، Real-time:

- **`GET /analytics/funnel?job_id=`** — قیف استخدام: آرایه‌ی مرتب `{stage, count}` برای `Applied → … → Hired`. `count` **تجمعی** است (چند درخواست به این مرحله رسیده یا از آن گذشته، از روی `status_history`) تا قیف همیشه نزولی باشد؛ `Draft` و `Rejected` عمداً جزو مراحل نیستند.
- **`GET /analytics/applications-trend?days=30&job_id=`** — تعداد درخواست‌های ثبت‌شده به تفکیک روز (`days` بین ۱ تا ۳۶۵)، با Zero-Filling روزهای خالی در بک‌اند. مبنا: ستون `applications.created_at` (مایگریشن `c39a7f1de204`؛ رکوردهای قدیمی از اولین ردیف `status_history` Backfill شدند).

### اطلاع‌رسانی ایمیلی

ارسال ایمیل کاملاً ناهمگام و از طریق صف Redis است — هیچ ایمیلی داخل یک درخواست HTTP فرستاده نمی‌شود.

| رویداد | ایمیل |
|---|---|
| ثبت‌نام کاربر | خوش‌آمدگویی |
| وضعیت → `Screening`, `Technical Interview`, `HR Interview` | تغییر وضعیت (`status_update.html`) |
| وضعیت → `Offer` | نامه‌ی پیشنهاد همکاری با دکمه‌های قبول/رد + پیوست PDF (`job_offer.html`) |
| وضعیت → `Rejected` (توسط HR) | عدم تأیید (`status_update.html`) |
| `forgot-password` | کد OTP (`otp_reset.html`) |
| ۲۴ ساعت پیش از مصاحبه | یادآور (`interview_reminder.html`) |

<details>
<summary>معماری و جزئیات</summary>

- `app/core/email_service.py`: تنها لایه‌ی متصل به SMTP (`smtplib`، همگام، با پشتیبانی پیوست) — فقط از داخل Taskهای پس‌زمینه.
- `app/tasks/notifications.py`: Taskهای ارسال که Worker اجرا می‌کند · `app/core/notification_service.py`: نمای سطح بالا برای روترها.
- `app/core/status_notifier.py`: هوک ماشین وضعیت → ایمیل. عمداً فقط به مسیر HR وصل است، نه به `respond` کارجو (لحن «متأسفانه رد شدید» برای ردِ خودِ کارجو معنا ندارد و او از تصمیم خودش باخبر است).
- قالب‌ها (`app/templates/emails/`) با Jinja2 و autoescape (امن در برابر HTML) و Layout مشترک `base.html`.
- PDF پیشنهاد همکاری با ReportLab (`app/core/offer_letter.py`).

</details>

### اعلان‌های داخل سایت و مسیرهای عملیاتی

| مسیر | دسترسی | توضیح |
|---|---|---|
| `GET /notifications/me` | هر کاربر لاگین‌شده | اعلان‌های خودِ کاربر (جدیدترین اول) + `unread_count` |
| `PUT /notifications/{id}/read` · `PUT /notifications/read-all` | هر کاربر | علامت‌گذاری خوانده‌شده |
| `POST /ops/alerts` | توکن `OPS_WEBHOOK_TOKEN` | وب‌هوک Alertmanager → اعلان برای همه‌ی اعضای تیم فنی |
| `POST /ops/events` | توکن `OPS_WEBHOOK_TOKEN` | گزارش CI/CD (`{title, content, level, category}`) → اعلان برای تیم فنی |

بدون تنظیم `OPS_WEBHOOK_TOKEN`، مسیرهای `/ops/*` با `503` کاملاً غیرفعال‌اند. در فرانت‌اند: داشبورد HR ← تب **«اعلان‌های فنی»** (به‌روزرسانی خودکار هر ۱۵ ثانیه + Toast فوری).

### سایر

- `GET /api/v1/health` — بررسی سلامت · `GET /metrics` — متریک‌های Prometheus (بیرون از `/api/v1`؛ در Production از بیرون بسته است).
- **کش و صف (Redis):** نشست کاربر ۵ دقیقه کش می‌شود (`app/core/cache.py`)؛ کارهای سنگین با RQ (`app/core/queue.py`) به‌صورت fire-and-forget به صف می‌روند. قطعی Redis سرور را از کار نمی‌اندازد — فقط کش/صف موقتاً غیرفعال می‌مانند.

---

## خط لوله‌ی هوش مصنوعی رزومه

بعد از هر آپلود موفق، Worker این چهار مرحله را در پس‌زمینه اجرا می‌کند (`app/tasks/resume_processing.py`). شکست هر مرحله فقط لاگ می‌شود و نتایج مراحل قبلی از بین نمی‌رود:

```
فایل رزومه ─► ① استخراج متن/OCR ─► ② پارسینگ و NER ─► ③ موتور مهارت ─► ④ نمره‌ی تطابق
              resumes.raw_text      resumes.parsed_data   resumes.skill_analysis   applications.score_ai
```

**① استخراج متن و OCR** (`app/core/text_extraction.py`)
- PDF: ابتدا لایه‌ی متنی با PyMuPDF؛ اگر به‌طرز مشکوکی کوتاه بود (رزومه‌ی اسکن‌شده)، هر صفحه به تصویر رندر و با **Tesseract** (فارسی + انگلیسی) خوانده می‌شود. DOCX مستقیم با `python-docx` (پاراگراف‌ها + جدول‌ها).
- فایل خراب/رمزدار → `UnreadableResumeFileError`: فقط همان رزومه متوقف می‌شود، Worker کرش نمی‌کند. متن نهایی پیش از ذخیره یکپارچه‌سازی می‌شود.

**② پارسینگ و NER** (`app/core/resume_parser.py`) — خروجی: `personal_info` (نام، ایمیل، تلفن)، `education[]` (مدرک، دانشگاه، معدل)، `work_experience[]` (شرکت، عنوان، بازه‌ی زمانی).
- رویکرد ترکیبی: موجودیت‌های الگودار (ایمیل، تلفن، معدل، تاریخ) با Regex؛ مرزبندی بخش‌ها با هدینگ‌های فارسی/انگلیسی؛ نام شرکت/دانشگاه و نام شخص با قواعد متنی («شرکت X»، «دانشگاه X») و در نبودشان با مدل NER **spaCy**.

**③ موتور مهارت** (`app/core/skill_engine.py`) — خروجی: `skills[]`، `total_experience_years`، `experience_entries[]` (با `is_valid` و `flag_reason`).
- **گراف مهارت** (`skill_graph.py`): زیرشاخه‌ها مهارت والد را هم اضافه می‌کنند (مثلاً FastAPI ← Python)؛ تطبیق با مرز کلمه (`java` داخل `javascript` تشخیص داده نمی‌شود).
- **تحلیل سوابق** (`experience_analyzer.py`): تشخیص خودکار تقویم شمسی/میلادی؛ دوره‌های متناقض، آینده‌دار یا بیش از ۴۰ سال فیلتر (ولی با دلیل در خروجی) می‌شوند؛ سابقه‌ی خالص با ادغام بازه‌های همپوشان (Merge Intervals) — دو شغل هم‌زمان دوبار حساب نمی‌شوند.

**④ نمره‌ی تطابق** (`app/core/matching_engine.py`) — عدد صحیح ۰ تا ۱۰۰ در `applications.score_ai`:

| بخش | وزن | تقسیم داخلی |
|---|---|---|
| مهارت‌های کلیدی/اجباری آگهی | ۵۰٪ | — (مهارت والد هم تطبیق حساب می‌شود) |
| عنوان شغلی + ارشدیت | ۳۰٪ | ۱۵٪ عنوان · ۱۵٪ سابقه نسبت به `required_seniority` |
| فاکتورهای تکمیلی | ۲۰٪ | ۸٪ تحصیلات · ۸٪ موقعیت مکانی · ۴٪ کلمات کلیدی ثانویه‌ی توضیحات آگهی |

تقسیم‌های داخلی انتخاب طراحی و قابل‌تغییر در ثابت‌های همان فایل‌اند. نبود داده (مثلاً `location` یا `required_education`) در هر دو طرف جریمه نمی‌شود. تست کلیدی: `tests/test_matching_engine.py::test_no_required_skill_match_deducts_exactly_fifty_percent`. (نام فیلد در تسک `ai_score` بود؛ برای حفظ یکپارچگی با بورد کانبان و فرانت‌اند، همان `score_ai` موجود حفظ شد.)

---

## زیرساخت: Docker، مانیتورینگ، CI/CD و استقرار

### ایمیج‌ها و Compose

- **بک‌اند (`Dockerfile`)** — پایه‌ی `python:3.11-slim`، دو مرحله: `builder` (ابزار کامپایل + نصب وابستگی‌ها در venv + مدل spaCy) و `production` (فقط venv + کد + Tesseract؛ بدون gcc/کش pip/تست/`.env`؛ کاربر غیر root؛ `PYTHONDONTWRITEBYTECODE=1`، `PYTHONUNBUFFERED=1`؛ پورت 8000 و Healthcheck). همین ایمیج با `command` متفاوت برای API، Worker، Scheduler و Migrate استفاده می‌شود.
- **فرانت‌اند (`frontend/Dockerfile`)** — `node:22-alpine` برای build، مرحله‌ی نهایی فقط `nginx:1.27-alpine` (پورت 80؛ `/api` و `/media` را به بک‌اند پراکسی می‌کند).
- **`docker-compose.yml`:** شبکه‌ی ایزوله‌ی `ats_network` (Bridge) — سرویس‌ها با **نام** هم را پیدا می‌کنند و PostgreSQL/Redis پورتی به بیرون باز نمی‌کنند · Volumeهای نام‌دار `postgres_data`، `redis_data` (با AOF)، `media_data`، `prometheus_data`، `grafana_data` · `depends_on` با `service_healthy`: بک‌اند فقط بعد از سالم شدن دیتابیس/Redis و اتمام `migrate` بالا می‌آید.

### مانیتورینگ و هشدار

```
backend /metrics · node · postgres · redis exporters ─► Prometheus ─► قوانین هشدار ─► Alertmanager
                                                            │                              │ POST /api/v1/ops/alerts
                                                            ▼                              ▼
                                                    Grafana (داشبورد زنده)      اعلان داخل سایت برای تیم فنی
```

- **متریک‌های بک‌اند** (`app/core/metrics.py`): `http_requests_total`، `http_request_duration_seconds`، `http_requests_in_progress`، `ats_rq_jobs{state}` (کارهای منتظر/در حال اجرا/ناموفق/زمان‌بندی‌شده)، `ats_rq_workers` + CPU/RAM پردازه. برچسب مسیر همیشه الگوی مسیر است (مثل `/api/v1/jobs/{job_id}`).
- **داشبوردهای Grafana** (خودکار provision، پوشه‌ی «ATS Smart»): **سلامت سیستم** (CPU، RAM، دیسک، شبکه، کانکشن‌ها و تراکنش‌های PostgreSQL، Redis، صف) و **کارایی API** (RPS، Latency p50/p95/p99، نرخ خطای 5xx، پرترافیک‌ترین و کندترین مسیرها). منبع: `monitoring/grafana/generate_dashboards.py` (بعد از تغییر، اجرایش کنید).

| هشدار (`monitoring/prometheus/alerts.yml`) | شرط | شدت |
|---|---|---|
| `HostHighMemoryUsage` | RAM بالای **۸۵٪** (۱ دقیقه) | critical |
| `ApiHighErrorRate` | نرخ خطای 5xx بالای **۵٪** (۱ دقیقه) | critical |
| `BackendDown` · `PostgresDown` · `RedisDown` · `NoQueueWorkers` | سرویس در دسترس نیست / Worker فعالی نیست | critical |
| `HostHighCpuUsage` · `ApiHighLatency` · `PostgresTooManyConnections` | CPU بالای ۸۵٪ (۵ دقیقه) · p95 بیش از ۱ ثانیه · کانکشن‌ها بالای ۸۰٪ | warning |
| `QueueBacklog` · `QueueJobsFailing` · `HostLowDiskSpace` · `ExporterDown` | بیش از ۵۰ کار منتظر · بیش از ۵ شکست در ۱۵ دقیقه · دیسک زیر ۱۰٪ · Exporter قطع | warning |

Alertmanager هر هشدار (و «برطرف شد») را با `OPS_WEBHOOK_TOKEN` به بک‌اند می‌فرستد؛ برای همه‌ی کاربران فعال با نقش‌های `OPS_ALERT_RECIPIENT_ROLES` اعلان ساخته می‌شود.

### خط لوله‌ی CI/CD (`.github/workflows/ci-cd.yml`)

```
lint (Black + Flake8) ─► test (Pytest + مایگریشن روی PostgreSQL/Redis واقعی) ─┐
frontend (TypeScript + Vite build) ────────────────────────────────────────┴─► build-and-push ─► deploy ─► report
```

- روی هر Push/PR به `develop`. شکست **هر** مرحله، مراحل بعدی را متوقف می‌کند — کد خراب به Docker Hub یا سرور نمی‌رسد.
- `build-and-push` و `deploy` فقط روی Push به `develop`؛ ایمیج‌ها با تگ `sha-<commit>` (برای Rollback) و `develop`.
- **گزارش:** Job Summary همان اجرا + اعلان در «اعلان‌های فنی» داخل سایت. تا وقتی Secrets انتشار/استقرار تنظیم نشده‌اند، آن مراحل با پیام توضیحی Skip می‌شوند.

<details>
<summary>GitHub Secrets لازم</summary>

| Secret | توضیح |
|---|---|
| `DOCKERHUB_USERNAME` · `DOCKERHUB_TOKEN` | Docker Hub ← Account Settings ← Personal access tokens (Read & Write) |
| `SSH_HOST` · `SSH_USER` · `SSH_PORT` (اختیاری، 22) | مشخصات سرور |
| `SSH_PRIVATE_KEY` | کلید خصوصی استقرار (کلید عمومی در `~/.ssh/authorized_keys` سرور) |
| `SSH_KNOWN_HOSTS` | خروجی `ssh-keyscan -p <port> <host>` (یک‌بار، از سیستم مطمئن) |
| `DEPLOY_PATH` (اختیاری) | مسیر پروژه روی سرور؛ پیش‌فرض `/opt/ats-smart` |
| `OPS_EVENTS_URL` · `OPS_WEBHOOK_TOKEN` | مثلاً `https://ats.example.com/api/v1/ops/events` · همان مقدار `.env` سرور |

</details>

### استقرار بدون قطعی (Zero-Downtime)

**آماده‌سازی یک‌باره‌ی سرور** (Docker Engine + Compose نسخه‌ی 2.24.4 به بالا):
```bash
sudo mkdir -p /opt/ats-smart && sudo chown $USER /opt/ats-smart
# فایل .env سرور بر اساس .env.example — حتماً: SECRET_KEY, POSTGRES_PASSWORD, OPS_WEBHOOK_TOKEN,
# GRAFANA_ADMIN_PASSWORD, PUBLIC_BASE_URL=https://ats.example.com, ENVIRONMENT=production, SMTP_*
```

از آن به بعد هر Push به `develop` (بعد از سبز شدن تست‌ها) خودکار مستقر می‌شود: CI فایل‌های زیرساخت را با SSH منتقل و `deploy/deploy.sh` را اجرا می‌کند.

1. در Production فقط `gateway` (Nginx) پورت عمومی دارد و در استقرار عادی جایگزین نمی‌شود (`deploy/docker-compose.prod.yml`).
2. برای `backend_api` و `frontend`، نسخه‌ی جدید **کنار** نسخه‌ی فعلی بالا می‌آید و تا Healthcheck سبز نشود ترافیک نمی‌گیرد.
3. Nginx نام سرویس‌ها را هر ۵ ثانیه از DNS داخلی Docker resolve می‌کند و با `proxy_next_upstream`، درخواستِ ردشده توسط کانتینر در حال خاموش‌شدن را بی‌صدا به کانتینر سالم می‌دهد.
4. نسخه‌ی قبلی با SIGTERM خاموش می‌شود؛ درخواست‌های در حال اجرا تا ۳۰ ثانیه کامل می‌شوند.
5. اگر نسخه‌ی جدید سالم نباشد: کانتینرهای جدید حذف، نسخه‌ی قبلی بدون وقفه ادامه می‌دهد و Pipeline قرمز می‌شود (Rollback خودکار).

- **مایگریشن‌ها** پیش از جایگزینی کد اجرا می‌شوند، پس باید با نسخه‌ی قبلی کد هم سازگار باشند (Expand/Contract): ستون جدید را ابتدا nullable/با پیش‌فرض اضافه کنید و حذف ستون‌های قدیمی را به انتشار بعدی موکول کنید.
- دستورات دستی روی سرور: `./deploy/compose.sh ps` · `./deploy/compose.sh logs -f backend_api`
- Grafana در Production: `https://<دامنه>/grafana/` · Prometheus/Alertmanager فقط از خود سرور (`127.0.0.1:9090` / `:9093`، مثلاً با SSH Tunnel).

---

## ساختار ریپو

```
├── app/
│   ├── main.py              # نقطه‌ی ورود (Middlewareها، روترها، /metrics، بررسی Redis در startup)
│   ├── worker.py            # Worker صف RQ (سازگار با ویندوز)
│   ├── routers/             # health, auth, admin, jobs, applications, resumes, candidates, interviews, analytics, notifications, ops
│   ├── schemas/             # اسکیماهای Pydantic (یک فایل به‌ازای هر روتر + resume_parsing, skill_analysis)
│   ├── models/              # ۱۴ جدول ORM: core (User, Company, Candidate, Job) · process (Application, Interview, Resume, Skill)
│   │                        #   · security (Role, Permission, Notification, Log, Audit, StatusHistory)
│   ├── core/                # منطق مشترک:
│   │   ├── config · security · deps · limiter · sanitize          # تنظیمات، JWT/Bcrypt، RBAC، Rate Limit، XSS
│   │   ├── state_machine · pagination · search_query · storage    # ماشین وضعیت، صفحه‌بندی نشانگر، جستجو، فایل
│   │   ├── redis_client · cache · queue · metrics                 # Redis، کش، صف RQ، متریک‌های Prometheus
│   │   ├── text_extraction · resume_parser · skill_graph · experience_analyzer · skill_engine · matching_engine
│   │   ├── email_service · email_templates · offer_letter · notification_service · status_notifier
│   │   └── interview_scheduler · candidate_utils · ops_notifier
│   ├── tasks/               # کارهای Worker: resume_processing (خط لوله‌ی AI)، notifications (ایمیل‌ها)
│   ├── templates/emails/    # قالب‌های HTML ایمیل
│   └── db/session.py        # اتصال Async به دیتابیس
├── alembic/                 # مایگریشن‌های دیتابیس
├── tests/                   # unit/ (تست‌های واحد) · integration/ (API + دیتابیس موقت)
├── frontend/                # فرانت‌اند React (+ Dockerfile و nginx.conf)
├── monitoring/              # Prometheus (+ alerts.yml)، Alertmanager، Grafana (provisioning + داشبوردها)
├── deploy/                  # docker-compose.prod.yml، deploy.sh، compose.sh، nginx/gateway.conf
├── .github/workflows/       # ci-cd.yml
├── Dockerfile · docker-compose.yml
├── requirements.txt         # وابستگی‌های Production
├── requirements-dev.txt     # + ابزارهای تست و Lint
└── pyproject.toml · .flake8 # تنظیمات Black/Pytest و Flake8
```

---

## محدودیت‌های شناخته‌شده

- **NER فارسی:** مدل `en_core_web_sm` انگلیسی است؛ برای متن فارسی فقط نقش کمکی دارد و استخراج فارسی عمدتاً به Regex و کلیدواژه تکیه دارد. برای دقت بالاتر، یک مدل NER فارسی در آینده پیشنهاد می‌شود.
- **تقویم:** تبدیل شمسی↔میلادی با افست ساده‌ی ۶۲۱ سال است (بدون کبیسه) و فرض شده هر رزومه فقط از یک تقویم استفاده می‌کند.
- **شرکت‌ها:** هنوز مسیری برای «ساخت شرکت» نیست؛ آگهی‌ها به‌جای `company_id` به سازنده‌شان (`created_by`) وصل‌اند.
- **مهارت‌ها:** تگ‌های مهارتی کارجو آرایه‌ای ساده روی `candidates` است؛ جدول `skills` فعلاً یک بانک خام بدون رابطه با کارجوهاست.
- **مصاحبه:** «اتاق مجازی» یعنی ثبت یک `meeting_link` از پیش‌ساخته (بدون یکپارچگی با API ویدئوکنفرانس)؛ چون `users` فیلد نام ندارد، «نام مصاحبه‌کننده» همان ایمیل اوست.
- **ایمیل پیشنهاد:** دکمه‌های قبول/رد به صفحه‌ی اصلی فرانت‌اند لینک می‌شوند (فرانت‌اند هنوز URL Routing ندارد)؛ محتوای PDF عمداً انگلیسی است (فونت‌های پیش‌فرض ReportLab حروف فارسی را درست شکل نمی‌دهند).
- **فرانت‌اند:** صفحه‌ی ورود هنوز ساخته نشده؛ توکن فعلاً دستی (از Swagger) وارد می‌شود.
- **هشدار BackendDown:** اگر خودِ بک‌اند از کار بیفتد، اعلان داخل سایت تا بالا آمدن دوباره‌ی آن تحویل نمی‌شود (Alertmanager تکرار می‌کند؛ در این مدت وضعیت در Grafana و Alertmanager دیده می‌شود).
- **HTTPS:** گواهی TLS در این ریپو پیکربندی نشده؛ آن را جلوی `gateway` قرار دهید (کوکی `refresh_token` با پرچم `Secure` فقط روی HTTPS کار می‌کند).
