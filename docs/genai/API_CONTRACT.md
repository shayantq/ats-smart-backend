# قرارداد API سرویس تولید سؤال مصاحبه با هوش مصنوعی مولد

**نسخه‌ی قرارداد:** 1.0 · **نسخه‌ی Prompt:** `interview-questions/v1` · **فاز:** ۲ نقشه‌ی راه (طراحی اولیه + PoC)

این سرویس برای هر «درخواست شغلی» (کارجو × آگهی) یک بانک سؤال اختصاصی می‌سازد: سؤال‌های تخصصی، هر کدام با کلید پاسخ، معیارهای ارزیابی، نشانه‌های پاسخ ضعیف و سؤال‌های پیگیری. سؤال‌ها بر اساس نقاط قوت و شکاف‌های واقعی کارجو نسبت به نیازمندی‌های آگهی طراحی می‌شوند.

فایل‌های ماشین‌خوان این قرارداد، از روی خودِ کد ساخته می‌شوند (`python -m app.genai.contract`). یک تست واحد هر اختلاف بین این فایل‌ها و کد را رد می‌کند:

| فایل | محتوا |
|---|---|
| [`openapi.json`](openapi.json) | OpenAPI 3.1 همه‌ی مسیرهای `/api/v1/genai` |
| [`interview-question-set.schema.json`](interview-question-set.schema.json) | JSON Schema خروجی مدل زبانی (همان Schema ارسالی در درخواست) |

---

## ۱. معماری

```
HR (داشبورد)                                         genai-worker (صف genai)
   │ POST /genai/interview-questions                       │
   ▼                                                       ▼
backend-api ──► interview_question_sets (pending) ──► Redis ──► پروفایل بدون اطلاعات شخصی
   │  ۲۰۲ + status_url                                              │ (رزومه‌ی تحلیل‌شده + آگهی + نقاط قوت/ضعف)
   │                                                               ▼
   │                                              سرویس مدل زبانی (Chat Completions + JSON Schema)
   │                                                               │
   │                                              اعتبارسنجی Schema ─(نامعتبر؟ یک بار اصلاح)
   │                                                               ▼
   └── GET status_url ◄────────────────── interview_questions (completed) ◄─┘
                                          ▲
Interviewer: بازبینی، ویرایش، تأیید ──────┘ ──► بانک سؤال مشترک (فقط تأییدشده‌ها)
```

- **ناهمگام:** پاسخ مدل ممکن است ده‌ها ثانیه طول بکشد، پس درخواست HTTP هرگز منتظر مدل نمی‌ماند. کار در صف `genai` و Worker جدای خودش اجرا می‌شود، تا ایمیل‌ها و پردازش رزومه معطل آن نمانند.
- **مستقل از ارائه‌دهنده:** سرویس فقط با پروتکل استاندارد Chat Completions حرف می‌زند (بخش ۶). سرویس مدل (ابری، یا سرور داخل کلاستر) فقط با سه تنظیم `GENAI_BASE_URL`، `GENAI_MODEL` و `GENAI_API_KEY` انتخاب می‌شود.
- **کد:**

| لایه | فایل |
|---|---|
| Prompt | `app/genai/prompts.py` |
| کلاینت | `app/genai/client.py` |
| هماهنگ‌سازی | `app/genai/service.py` |
| Worker | `app/tasks/genai.py` |
| API | `app/routers/genai.py` |
| Schema | `app/schemas/genai.py` |
| جداول | `app/models/genai.py` + مایگریشن `a7c3e91f0b42` |

---

## ۲. احراز هویت و دسترسی

همه‌ی مسیرها توکن `Authorization: Bearer <access_token>` می‌خواهند (همان `POST /api/v1/auth/login`).

| نقش | درخواست تولید | دیدن بانک سؤال یک درخواست | ویرایش/تأیید سؤال | بانک سؤال مشترک |
|---|---|---|---|---|
| `Admin`، `HR_Manager` | ✔ | ✔ همه | ✔ | ✔ |
| `Interviewer` | ✘ | فقط درخواست‌هایی که مصاحبه‌شان به خودش سپرده شده | همان‌ها | ✔ |
| `Candidate` | ✘ | ✘ — کلید پاسخ‌ها هرگز به کارجو نمی‌رسد | ✘ | ✘ |

---

## ۳. مسیرها

مسیرها با پیشوند `/api/v1/genai` هستند. فهرست‌ها همان صفحه‌بندی مبتنی بر نشانگر کل API را دارند (پارامترهای `cursor`، `direction=next|prev` و `limit`).

### ۳-۱. `POST /interview-questions` — درخواست تولید (ناهمگام)

بدنه:
```json
{
  "application_id": "6f2c…-…",
  "question_count": 8,
  "difficulty": "mixed",
  "focus_skills": ["Kafka", "Kubernetes"],
  "language": "fa"
}
```

| فیلد | نوع | الزامی | قواعد |
|---|---|---|---|
| `application_id` | UUID | ✔ | درخواست شغلی موجود، با رزومه‌ی تحلیل‌شده |
| `question_count` | int | — | ۳ تا ۱۵ (پیش‌فرض ۸) |
| `difficulty` | enum | — | `mixed` (پیش‌فرض: حدود ۳۰٪ آسان، ۴۵٪ متوسط، ۲۵٪ سخت)، `easy`، `medium`، `hard` |
| `focus_skills` | string[] | — | حداکثر ۱۰ مهارت؛ هر کدام حداقل یک سؤال می‌گیرد |
| `language` | enum | — | `fa` (پیش‌فرض؛ اصطلاحات فنی انگلیسی می‌ماند) یا `en` |

فیلد ناشناخته پذیرفته نمی‌شود و `422` برمی‌گرداند.

پاسخ `202 Accepted`:
```json
{ "id": "1b9d…", "status": "pending", "status_url": "/api/v1/genai/interview-questions/1b9d…" }
```

| کد | معنا |
|---|---|
| `202` | ثبت شد و در صف `genai` قرار گرفت |
| `401` · `403` | توکن نامعتبر · نقش غیرمجاز |
| `404` | درخواست شغلی پیدا نشد |
| `409` | رزومه‌ی کارجو هنوز تحلیل نشده (`skill_analysis` ندارد) |
| `422` | بدنه‌ی نامعتبر |
| `503` | سرویس مدل پیکربندی نشده (`GENAI_BASE_URL`/`GENAI_MODEL` خالی)، یا صف در دسترس نیست. در حالت دوم بانک سؤال با وضعیت `failed` ثبت می‌شود |

### ۳-۲. `GET /interview-questions/{set_id}` — وضعیت و سؤال‌ها

چرخه‌ی وضعیت: `pending → processing → completed | failed`. تا وقتی وضعیت `completed` نشده، فهرست `questions` خالی است. پیشنهاد Polling: هر ۳ تا ۵ ثانیه.

```json
{
  "id": "1b9d…", "application_id": "6f2c…", "job_id": "…", "candidate_id": "…",
  "status": "completed", "language": "fa", "question_count": 8, "difficulty": "mixed",
  "focus_skills": ["Kafka"], "prompt_version": "interview-questions/v1",
  "focus_summary": "تمرکز بر عمق PostgreSQL و FastAPI، و سنجش فاصله با Kafka و Kubernetes",
  "error": null,
  "usage": { "prompt_tokens": 1830, "completion_tokens": 2410, "latency_ms": 41250 },
  "created_at": "2026-10-19T10:00:00Z", "completed_at": "2026-10-19T10:00:42Z",
  "questions": [
    {
      "id": "…", "position": 1,
      "category": "gap_probe", "skill": "Kafka", "difficulty": "medium",
      "question": "اگر بخواهید رویدادهای ثبت درخواست را بین چند سرویس پخش کنید، با تجربه‌ی Redis خود چه راه‌حلی می‌سازید و Kafka چه چیزی اضافه می‌کند؟",
      "purpose": "شکاف: مهارت اجباری Kafka در رزومه نیست؛ سنجش دانش انتقال‌پذیر از Redis",
      "expected_answer": "Pub/Sub یا Stream در Redis … Kafka: ماندگاری لاگ، پارتیشن و Consumer Group، بازپخش رویداد …",
      "evaluation_points": ["تفاوت صف و لاگ رویداد", "پارتیشن و ترتیب پیام", "Consumer Group"],
      "red_flags": ["یکی دانستن Kafka با صف ساده"],
      "follow_ups": ["تضمین at-least-once را چطور مدیریت می‌کنید؟"],
      "estimated_minutes": 6,
      "is_approved": false, "interviewer_notes": null, "updated_at": null
    }
  ]
}
```

در وضعیت `failed`، فیلد `error` دلیل خطا را نشان می‌دهد؛ مثلاً «سقف توکن خروجی»، «خروجی پس از اصلاح هم با Schema سازگار نبود» یا «خطای 401 سرویس».

### ۳-۳. `GET /interview-questions?application_id=` — فهرست بانک‌های سؤال یک درخواست

فهرست جدیدترین‌ها اول است. هر آیتم همان ساختار ۳-۲ را دارد.

### ۳-۴. `PATCH /interview-questions/{set_id}/questions/{question_id}` — بازبینی مصاحبه‌کننده

```json
{ "question": "…", "expected_answer": "…", "is_approved": true, "interviewer_notes": "مناسب سطح Senior" }
```

- همه‌ی فیلدها اختیاری‌اند؛ فقط فیلدهای ارسال‌شده تغییر می‌کنند.
- تگ‌های HTML حذف می‌شوند (دفاع در برابر XSS).
- پاسخ سؤال به‌روزشده است، و `updated_at` و ویرایشگر (`updated_by`) ثبت می‌شوند.
- `is_approved: true` سؤال را وارد بانک سؤال مشترک می‌کند.

### ۳-۵. `GET /question-bank?skill=&difficulty=&category=` — بانک سؤال مشترک

فقط سؤال‌های **تأییدشده** را برمی‌گرداند. جست‌وجوی مهارت بدون حساسیت به حروف است (`postgresql` همان `PostgreSQL` است). ایندکس جزئی `ix_interview_questions_approved_skill` این جست‌وجو را پشتیبانی می‌کند. هر آیتم = ساختار سؤال + `question_set_id` + `job_id`.

---

## ۴. JSON Schema خروجی مدل

فایل کامل: [`interview-question-set.schema.json`](interview-question-set.schema.json). ساخته‌شده از `GeneratedQuestionSet` در `app/schemas/genai.py`، بدون `$ref`، با همه‌ی فیلدهای اجباری و `additionalProperties: false` (سازگار با خروجی مقید «strict»).

| فیلد | نوع | قید |
|---|---|---|
| `focus_summary` | string | ۱۰ تا ۱۵۰۰ نویسه — محورهای مصاحبه |
| `questions[]` | array | ۱ تا ۱۵ (در هر درخواست: `minItems = maxItems` = طول نقشه‌ی سؤال‌ها) |
| `└ category` | enum | `technical` · `problem_solving` · `system_design` · `behavioral` · `gap_probe` |
| `└ skill` | string | ≤۱۰۰، نام کوتاه انگلیسی |
| `└ difficulty` | enum | `easy` · `medium` · `hard` |
| `└ question` | string | ۱۰ تا ۱۲۰۰ |
| `└ purpose` | string | ارجاع به نقطه‌ی قوت یا شکاف مشخص |
| `└ expected_answer` | string | کلید پاسخ، ۱۰ تا ۲۵۰۰ |
| `└ evaluation_points` | string[] | ۱ تا ۶ معیار نمره‌دهی |
| `└ red_flags` | string[] | ۰ تا ۴ |
| `└ follow_ups` | string[] | ۰ تا ۳ |
| `└ estimated_minutes` | int | ۱ تا ۳۰ |

**پردازش پاسخ:**
1. Markdown احتمالی دور JSON حذف و پاسخ با Pydantic اعتبارسنجی می‌شود.
2. اگر پاسخ نامعتبر بود، **یک بار** همراه با فهرست خطاهای Schema به مدل برگردانده می‌شود تا اصلاحش کند.
3. اگر باز هم نامعتبر بود، وضعیت `failed` ثبت می‌شود. تکرار بی‌پایان در کار نیست.
4. اگر تعداد سؤال‌ها کمتر از نقشه باشد، پاسخ نامعتبر حساب می‌شود (همان مسیر اصلاح). سؤال‌های اضافه کنار گذاشته می‌شوند.

---

## ۵. طراحی Prompt

**ورودی‌ها** (`build_input_profile`) از خروجی موتورهای موجود ساخته می‌شوند، نه از متن خام:

| بلوک | منبع |
|---|---|
| `<job_posting>` | عنوان، ارشدیت، تحصیلات، مهارت‌های اجباری، شرح (تا ۲۰۰۰ نویسه) |
| `<candidate_profile>` | مهارت‌ها (موتور مهارت + تگ‌های پروفایل)، سابقه‌ی خالص، عنوان و بازه‌ی شغل‌ها، مدرک، نمره‌ی تطابق |
| `<fit_analysis>` | **نقاط قوت و شکاف‌ها با محاسبه‌ی قطعی کد** (جدول زیر) |
| `<resume_excerpt>` | ۱۵۰۰ نویسه‌ی اول رزومه، پاک‌سازی‌شده — داده‌ی غیرقابل‌اعتماد |
| `<question_plan>` | **نقشه‌ی قطعی سؤال‌ها** (`plan_questions`): دسته، مهارت و سختی هر سؤال |

| سیگنال | قوت/ضعف |
|---|---|
| مهارت اجباری با تطبیق دقیق | قوت → سؤال عمیق برای سنجش تجربه‌ی واقعی |
| مهارت اجباری فقط از راه مهارت والد (مثلاً DevOps برای Kubernetes) | **شکاف جزئی**. برای نمره‌ی تطابق کافی است، ولی برای مصاحبه اثبات‌شده نیست |
| مهارت اجباری گم‌شده | شکاف → سؤال `gap_probe` (دانش انتقال‌پذیر، روش یادگیری) |
| مهارت اضافه‌ای که در شرح آگهی آمده | قوت |
| سابقه نسبت به ارشدیت (همان بازه‌های موتور تطابق) | قوت یا شکاف |
| مدرک پایین‌تر از نیاز آگهی | شکاف |
| دوره‌ی کاری مشکوک (پرچم تحلیل‌گر سابقه) | شکاف → سؤال راستی‌آزمایی |

**نقشه‌ی سؤال‌ها (`QuestionSlot`):** «چه چیزی پرسیده شود» را کد تعیین می‌کند و مدل فقط متن سؤال، کلید پاسخ و معیارها را می‌نویسد. در PoC اول، مدل دستور «برای هر شکاف یک سؤال» را نادیده گرفت و ۵ سؤال به‌جای ۶ برگرداند؛ با نقشه، پوشش شکاف‌ها به سلیقه‌ی مدل وابسته نیست.

| اولویت | ردیف نقشه |
|---|---|
| ۱ | `gap_probe` برای هر شکاف (جزئی یا گم‌شده)، حداکثر نیمی از سؤال‌ها |
| ۲ | `technical` برای مهارت‌های درخواستی HR (`focus_skills`) |
| ۳ | `technical` برای مهارت‌های اجباریِ تطبیق‌خورده. اولی `easy` (گرم‌کردن)، بقیه در سطح ارشدیت آگهی (`hard` برای Senior به بالا) |
| ۴ | `system_design` برای نقش‌های Mid به بالا |
| ۵ | `behavioral` (همکاری و مسئولیت‌پذیری) |
| ۶ | `problem_solving` روی مهارت‌های اضافه، تا رسیدن به `question_count` |

- ترتیب نهایی، ترتیب برگزاری مصاحبه است: فنی ← حل مسئله ← طراحی سیستم ← شکاف‌ها ← رفتاری.
- اگر `difficulty` ثابت باشد (نه `mixed`)، روی همه‌ی ردیف‌ها اعمال می‌شود.
- نقشه قطعی است (ورودی یکسان ← نقشه‌ی یکسان) و در `input_profile.question_plan` ذخیره می‌شود.

**قواعد پیام system:**
- هر سؤال باید به یک قوت یا شکاف مشخص در `fit_analysis` ارجاع بدهد.
- ردیف‌های `<question_plan>` به همان ترتیب رعایت می‌شوند.
- سؤال درباره‌ی ویژگی‌های حمایت‌شده ممنوع است: سن، جنسیت، مذهب، قومیت، ملیت، تأهل، سلامت، معلولیت، دیدگاه سیاسی.
- خروجی فقط JSON مطابق Schema است.

پیام‌ها انگلیسی‌اند، چون پایبندی مدل‌ها به دستور و Schema در انگلیسی دقیق‌تر است. زبان متن خروجی با `language` تعیین می‌شود.

**حریم خصوصی:**
- نام، ایمیل، تلفن (قالب‌های ایران و بین‌المللی، با ارقام فارسی یا لاتین) و نشانی‌های اینترنتی هرگز به مدل فرستاده نمی‌شوند. نام دانشگاه و شرکت هم فرستاده نمی‌شود.
- بازه‌ی سال‌ها (مثل `2018 - 2023`) عمداً حفظ می‌شود.
- پروفایل ارسالی عیناً در `input_profile` ذخیره می‌شود، برای ممیزی و بازتولید.

**Prompt Injection:**
- متن رزومه داخل برچسب جدا قرار می‌گیرد.
- برچسب‌های هم‌نام (`</resume_excerpt>`، `<question_plan>`، `<system>`، …) از خودِ متن حذف می‌شوند.
- دستور صریحی داده می‌شود که هر دستور داخل رزومه نادیده گرفته شود.

**نسخه‌بندی:** هر تغییر معنادار Prompt، `PROMPT_VERSION` را بالا می‌برد. نسخه کنار هر بانک سؤال ذخیره می‌شود تا کیفیت نسخه‌ها قابل مقایسه باشد.

---

## ۶. قرارداد با سرویس مدل زبانی (Chat Completions)

```http
POST {GENAI_BASE_URL}/chat/completions
Authorization: Bearer {GENAI_API_KEY}        ← فقط اگر کلید تنظیم شده باشد
Content-Type: application/json

{
  "model": "{GENAI_MODEL}",
  "messages": [{"role": "system", "content": "…"}, {"role": "user", "content": "…"}],
  "temperature": 0.3,
  "max_tokens": 4096,
  "response_format": {
    "type": "json_schema",
    "json_schema": {"name": "interview_question_set", "strict": true, "schema": { … }}
  }
}
```

پاسخ مورد انتظار: `choices[0].message.content` (متن JSON) و `choices[0].finish_reason`. فیلد `usage.prompt_tokens/completion_tokens` اختیاری است و در `usage` بانک سؤال ذخیره می‌شود.

| تنظیم | پیش‌فرض | توضیح |
|---|---|---|
| `GENAI_BASE_URL` | — | نشانی پایه تا `/v1` |
| `GENAI_MODEL` | — | شناسه‌ی مدل همان سرویس |
| `GENAI_API_KEY` | خالی | برای سرویس‌های ابری |
| `GENAI_STRUCTURED_OUTPUT` | `json_schema` | `json_object` برای سرویس‌هایی که خروجی مقید به Schema ندارند (اعتبارسنجی فقط سمت ما) |
| `GENAI_TIMEOUT_SECONDS` · `GENAI_MAX_OUTPUT_TOKENS` · `GENAI_TEMPERATURE` | `240` · `4096` · `0.3` | برای مدل CPU محلی، Timeout را `540` بگذارید (`genai.env.example`) |

| خطای سرویس | رفتار |
|---|---|
| قطعی شبکه، Timeout، `408/409/425/429/5xx` | قابل تکرار: وضعیت `pending` می‌ماند و صف RQ با فاصله‌ی ۳۰ ثانیه و ۲ دقیقه تکرار می‌کند. بعد از ۳ تلاش، وضعیت `failed` |
| سایر `4xx` (کلید نامعتبر، مدل ناموجود) | بدون تکرار → `failed` |
| `finish_reason = length` | `failed`: سقف توکن را بالا ببرید یا تعداد سؤال را کم کنید |

کلید API هرگز لاگ یا ذخیره نمی‌شود. شناسه‌ی مدل (`provider_model`) برای ممیزی کنار هر بانک سؤال ثبت می‌شود.

**اجرای محلی بدون کلید:**
- `k8s/overlays/local/genai-inference` یک سرور مدل متن‌باز را روی CPU داخل همان کلاستر بالا می‌آورد، با همین پروتکل و پشتیبانی `json_schema`.
- داده‌ی رزومه هرگز از سرور بیرون نمی‌رود.
- نشانی وزن‌های مدل فقط در `model.env` محلی است (در `.gitignore`).

---

## ۷. پایگاه داده

**`interview_question_sets`** — هر درخواست تولید

| ستون | نوع | توضیح |
|---|---|---|
| `id` | UUID PK | |
| `application_id` → `applications` (CASCADE) · `job_id` · `candidate_id` · `requested_by` → `users` | UUID FK | |
| `status` | varchar(20) + CHECK | `pending` · `processing` · `completed` · `failed` |
| `language` · `question_count` · `difficulty` · `focus_skills text[]` | | تنظیمات درخواست |
| `prompt_version` · `provider_model` | varchar | ممیزی |
| `input_profile` | JSONB | پروفایل ارسالی به مدل (بدون اطلاعات شخصی) |
| `focus_summary` · `error` | text | |
| `prompt_tokens` · `completion_tokens` · `latency_ms` · `attempts` | int | هزینه و کارایی |
| `created_at` · `completed_at` | timestamptz | |

ایندکس: `(application_id, created_at)`.

**`interview_questions`** — بانک سؤال

| ستون | نوع | توضیح |
|---|---|---|
| `id` | UUID PK | |
| `question_set_id` → `interview_question_sets` (CASCADE) · `position` | | یکتا: `(question_set_id, position)` |
| `category` · `skill` · `difficulty` (+ CHECK) | varchar | |
| `question` · `purpose` · `expected_answer` | text | |
| `evaluation_points` · `red_flags` · `follow_ups` | JSONB | فهرست‌ها |
| `estimated_minutes` | int | |
| `is_approved` · `interviewer_notes` · `updated_by` → `users` · `updated_at` | | بازبینی انسانی |

ایندکس جزئی: `(lower(skill), difficulty) WHERE is_approved` — جست‌وجوی بانک سؤال مشترک.

---

## ۸. اثبات مفهوم (PoC)

```bash
# همان خط لوله‌ی واقعی (استخراج متن ← پارسر ← موتور مهارت ← تطابق ← Prompt ← مدل ← Schema)، بدون دیتابیس
python -m app.genai.poc --resume docs/genai/samples/resume-backend.txt --job docs/genai/samples/job-senior-backend.json
python -m app.genai.poc ... --dry-run      # فقط پروفایل و Prompt، بدون فراخوانی مدل
# روی سرور مدل داخل کلاستر (از سیستم توسعه‌دهنده):
kubectl -n ats-smart port-forward svc/genai-inference 18080:8080 &
GENAI_BASE_URL=http://127.0.0.1:18080/v1 GENAI_MODEL=ats-interview-model python -m app.genai.poc --resume … --job …
# مسیر کامل API (آپلود رزومه ← پردازش ← تولید ← بازبینی):
bash k8s/genai-poc.sh
```

- **ورودی:** رزومه (PDF، DOCX یا TXT) و آگهی (JSON با همان فیلدهای `POST /api/v1/jobs/`).
- **خروجی:** JSON مطابق بخش ۴، به‌همراه `fit_analysis` و خلاصه‌ی زمان و توکن.
- نمونه‌ها: `docs/genai/samples/` (رزومه و آگهی ساختگی، و خروجی واقعی PoC).

**نتیجه‌ی PoC روی مدل محلی (۱.۵ میلیارد پارامتر، Q4، فقط CPU):**

| اجرا | زمان | توکن ورودی/خروجی | اصلاح خروجی | نتیجه |
|---|---|---|---|---|
| `--language fa` → `poc-output.fa.json` | ۲۷۱ ثانیه | ۱۷۰۶ / ۲۲۱۰ | خیر | ۶ سؤال معتبر، مطابق نقشه |
| `--language en` → `poc-output.en.json` | ۵۳۸ ثانیه | ۱۶۹۲ / ۱۴۶۹ | خیر | ۶ سؤال معتبر، مطابق نقشه |

نقشه‌ی هر دو اجرا: Python (`easy`) · FastAPI · PostgreSQL (`hard`) · طراحی سیستم (`hard`) · Kubernetes و Kafka (`gap_probe`). یعنی شکاف جزئی (Kubernetes فقط از راه DevOps) و مهارت گم‌شده (Kafka) هر دو پوشش داده شدند.

---

## ۹. محدودیت‌ها و قدم‌های بعدی

- **کیفیت سؤال به مدل بستگی دارد.** مدل کوچک متن‌باز روی CPU، ساختار، Schema و نقشه را کامل رعایت می‌کند، ولی متن سؤال‌ها کلی و تکراری است و فارسی‌اش ضعیف است. زمان هم ۴.۵ تا ۹ دقیقه برای ۶ سؤال است. برای Production یک مدل بزرگ‌تر (ابری یا GPU داخلی) پیشنهاد می‌شود؛ فقط تنظیمات عوض می‌شود.
- **ارزیابی کیفیت:** هنوز مجموعه‌ی ارزیابی (Eval) خودکار وجود ندارد. قدم بعدی: نمونه‌ی برچسب‌خورده از رزومه‌ها و سنجش ارتباط سؤال با شکاف‌ها، درستی کلید پاسخ و نبود سؤال ممنوع، برای مقایسه‌ی نسخه‌های Prompt.
- **هزینه:** مصرف توکن هر بانک سؤال ذخیره می‌شود. سقف و گزارش هزینه‌ی ماهانه هنوز پیاده نشده است.
- **رابط کاربری:** این فاز فقط API است. صفحه‌ی بازبینی سؤال‌ها در داشبورد HR و مصاحبه‌کننده، قدم بعدی است.
- **انتخاب رزومه:** جدول `resumes` ستون زمانی ندارد، پس برای کارجوی چندرزومه‌ای، رزومه‌ای با کامل‌ترین تحلیل مهارت استفاده می‌شود.
