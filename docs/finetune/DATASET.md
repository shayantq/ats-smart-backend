# دیتاست آموزش تکمیلی (Fine-Tuning) — جفت‌های «رزومه ↔ آگهی شغلی»

هدف: تبدیل داده‌ی خام دیتابیس به یک دیتاست دستوری (Instruction) ناشناس‌شده تا مدل زبانی اصطلاحات بازار کار
داخلی، عناوین شغلی و ظرافت‌های رزومه‌های فارسی/انگلیسی را یاد بگیرد. کد: `app/datasets/finetune/`.

## خط لوله

```
PostgreSQL (READ ONLY + system_scope، Cursor سمت سرور، دسته‌های ۵۰۰تایی)
  └─ extract.py     جفت‌های واجد شرایط: Application ⋈ Job ⋈ Candidate ⋈ User ⋈ Resume(agent_analysis)
       └─ cleanse.py   قوانین حذف رکورد ناقص/پرت + نرمال‌سازی (text_clean.py) + ناشناس‌سازی (anonymize.py)
            └─ records.py  instruction / input / output
                 └─ split.py    تقسیم گروهی و لایه‌بندی‌شده ۸۰/۱۰/۱۰
                      └─ build.py   train.jsonl, validation.jsonl, test.jsonl, manifest.json, stats.json
validate.py ── اعتبارسنج مستقل روی همان پوشه (کد خروج غیرصفر با هر خطا)
```

### شرایط ورود یک جفت

- حساب کارجو فعال است، رضایت پردازش داده داده (`users.data_consent_at` پر) و ناشناس نشده (`users.anonymized_at` خالی).
- اتصال دیتابیس در دو لایه فقط‌خواندنی است: تراکنش `READ ONLY` و `default_transaction_read_only=on` روی خود اتصال.
- رزومه‌ی کارجو در همان سازمانِ آگهی، خروجی اکوسیستم چندعاملی (`resumes.agent_analysis`) دارد.
- گیت حداقل تعداد: اگر تعداد جفت‌های واجد شرایط کمتر از `--min-pairs` (پیش‌فرض ۱۰٬۰۰۰) باشد، هیچ فایلی نوشته
  نمی‌شود و برنامه با کد ۲ و پیامی که فقط شامل عدد است خارج می‌شود.

**پیوند درخواست به رزومه:** جدول `resumes` کلید خارجی به `applications` ندارد. اگر کارجو در آن سازمان فقط یک رزومه‌ی
پردازش‌شده دارد همان انتخاب می‌شود؛ اگر چند تا، رزومه‌ای که `round(agent_analysis.matching.score) == score_ai`
(همان مقداری که Worker ذخیره کرده). اگر دقیقاً یکی جور نشد، رکورد با قانون `ambiguous_resume_link` کنار می‌رود.

## ساختار هر رکورد (JSONL، دقیقاً سه کلید)

| کلید | محتوا |
|------|-------|
| `instruction` | پرامپت ارزیابی فارسی ثابت، نسخه‌ی `hr-eval-v1` (نسخه در `stats.json`) |
| `input` | آگهی (عنوان، دپارتمان، ارشدیت، تحصیلات، مهارت‌های لازم، شرح) + متن ناشناس‌شده‌ی رزومه |
| `output` | رشته‌ی JSON قطعی: `score`، `verdict`، `matched_skills`، `missing_skills`، `experience`، `soft_skills`، `flags`، `hr_outcome`، `rationale` |

`output` بدون هیچ مدل زبانی و فقط از `agent_analysis` (قرارداد `agents-v1`) + `applications.score_ai` ساخته می‌شود.
`hr_outcome` نتیجه‌ی واقعی HR است: وضعیت درخواست (به‌جز Draft) و میانگین نمره‌ی مصاحبه‌ها.
عمداً حذف‌شده: `evidence` هشدارها و شاهدهای مهارت نرم (تکه‌ی خام متن)، شناسه‌های داخلی، `file_url`، زمان‌بندی عامل‌ها.

### نمونه‌ی کاملاً ساختگی

`input`:

```
## آگهی شغلی
عنوان: Backend Developer
دپارتمان: فنی
سطح ارشدیت: senior
تحصیلات لازم: کارشناسی
مهارت‌های لازم: Python، FastAPI، PostgreSQL، Kubernetes
شرح:
توسعه‌ی سرویس‌های پرداخت. برای سؤال با [EMAIL] یا [PHONE] تماس بگیرید.

## رزومه
[NAME]
ایمیل: [EMAIL] | تلفن: [PHONE]
LinkedIn: [URL] | Telegram: [URL]
تاریخ تولد: [BIRTH_DATE] | کد ملی: [NATIONAL_ID] | کد پستی: [POSTAL_CODE]
محل سکونت: [LOCATION]

خلاصه
برنامه‌نویس بک‌اند علاقه‌مند به سیستم‌های پایدار. [NAME] is a team player.

سوابق کاری
برنامه‌نویس بک‌اند — فناوران ابری سپهر (1398/01/01 - 1402/06/30)
- طراحی سرویس پرداخت با Python و FastAPI و کاهش زمان پاسخ
...
```

`output`:

```json
{
  "score": 78,
  "verdict": "مناسب",
  "matched_skills": ["Python", "FastAPI", "PostgreSQL"],
  "missing_skills": ["Kubernetes"],
  "experience": {
    "total_years": 7.0,
    "positions": [{"job_title": "برنامه‌نویس بک‌اند", "company": "فناوران ابری سپهر", "duration": "4 سال"}],
    "overlaps": 0,
    "invalid_periods": 1
  },
  "soft_skills": ["کار تیمی"],
  "flags": [{"code": "invalid_period", "severity": "low", "message": "یک بازه‌ی کاری نامعتبر است"}],
  "hr_outcome": {"status": "Technical Interview", "interview_score": 8.25},
  "rationale": "نمره‌ی تطابق 78 از 100 (مناسب). 3 از 4 مهارت لازم آگهی در رزومه دیده شد. مهارت‌های غایب: Kubernetes. سابقه‌ی کاری معتبر: 7.0 سال. 1 هشدار اعتبارسنجی برای بررسی HR ثبت شد."
}
```

## ناشناس‌سازی (anonymize.py)

۱. **مقدار دقیق شناسه‌های همان رکورد** (رمزگشایی‌شده فقط در حافظه): نام و نام خانوادگی پروفایل، نام استخراج‌شده
   توسط پارسر و خط اول رزومه وقتی شبیه نام است (۲ تا ۴ کلمه‌ی بدون رقم که عنوان شغلی/«رزومه» نیست) ← `[NAME]`.
   نام‌ها با همان نرمال‌سازی متن رزومه یکسان می‌شوند (ي/ك، ارقام) و هر کلمه جدا به‌علاوه‌ی شکل چسبیده‌ی نام
   چندکلمه‌ای («محمد رضا» ← «محمدرضا») جایگزین می‌شود. بخش محلی ایمیل؛ تلفن پروفایل (حتی با ارقام فارسی) با هر
   فاصله‌گذاری ← `[PHONE]`؛ شهر کارجو (فقط در متن رزومه؛ شهر آگهی سیگنال شغلی است) ← `[LOCATION]`.
۲. **الگوهای عمومی** (روی متن آگهی و فیلدهای خروجی هم):
   - ایمیل ← `[EMAIL]`
   - تلفن ← `[PHONE]`: هر دنباله‌ی رقمی با جداکننده‌ی دلخواه (فاصله، `-`، `/`، `.`، پرانتز، نیم‌فاصله) که از نظر
     تعداد رقم و پیش‌شماره موبایل یا ثابت ایران (`09xx`، `+98`، `0098`، `021`) یا شماره‌ی بین‌المللی (`+`/`00`)
     باشد، و هر عدد بعد از برچسب «تلفن/تماس/موبایل/phone/tel». بازه‌ی سال‌ها و مبالغ دست نمی‌خورند.
   - نشانی وب ← `[URL]`: `http(s)://`، `www.`، هر دامنه با پسوند رایج (`.com`، `.ir`، `.io`، ...) و `*.net/مسیر`،
     و شناسه‌ی `@handle`. نام فناوری‌های دامنه‌شکل (`ASP.NET`، `Socket.io`، ...) حفظ می‌شوند.
   - کد ملی (۱۰ رقم، با یا بدون فاصله/خط تیره) ← `[NATIONAL_ID]`؛ کد پستی ← `[POSTAL_CODE]`
   - تاریخ تولد کنار برچسب‌های «تاریخ تولد/سال تولد/متولد/تولد/born/birth/DOB» ← `[BIRTH_DATE]` (تاریخ‌های سوابق
     کاری بدون این برچسب حفظ می‌شوند)
   - خط برچسب‌دار نشانی «آدرس/نشانی/محل سکونت/Address:» ← `[ADDRESS]`
۳. **خودآزمایی پیش از نوشتن:** اگر پس از ناشناس‌سازی هنوز الگو یا هش شناسه‌ای در رکورد بماند، رکورد با قانون
   `pii_residual` حذف می‌شود.

`manifest.json` به ازای هر سطر هر بخش، هش HMAC (کلید `PII_BLIND_INDEX_KEY`، همان ایندکس کور جستجو) توکن‌های
شناسه‌ی همان رکورد و هش گروه کارجو را دارد — بدون هیچ متن ساده. فقط اعتبارسنج از آن استفاده می‌کند و
**نباید همراه دیتاست از سرور خارج شود.**

محدودیت شناخته‌شده: اگر نام کارجو در رزومه با املایی آمده باشد که در پروفایل و خروجی پارسر نیست (مثلاً
آوانویسی دیگری از نام فارسی)، لایه‌ی مقدار دقیق آن را نمی‌شناسد.

## پاک‌سازی داده (cleanse.py)

اولین قانونی که رکورد را رد کند در `stats.json → dropped` شمرده می‌شود:

| قانون | شرط حذف |
|-------|---------|
| `ambiguous_resume_link` | رزومه‌ی متناظر درخواست قابل تشخیص نیست |
| `incomplete_resume_text` / `incomplete_job` | متن رزومه خالی / عنوان و شرح آگهی هر دو خالی |
| `missing_score` / `missing_agent_analysis` | `score_ai` یا تحلیل چندعاملی ندارد (یا تحلیل کاملاً ناموفق) |
| `outlier_score` | نمره خارج از ۰ تا ۱۰۰ |
| `outlier_experience_years` | سابقه‌ی منفی یا بیش از `--max-experience-years` (۵۰) |
| `mojibake` | متن با کدگذاری اشتباه که تعمیرپذیر نبود |
| `outlier_resume_too_short` / `_too_long` | متن نرمال‌شده خارج از `--min-resume-chars` (۲۰۰) تا `--max-resume-chars` (۱۵٬۰۰۰) |
| `duplicate_exact` / `duplicate_near` | input تکراری دقیق / تقریبی (فقط حروف، بدون ارقام، فاصله، علائم و حروف بزرگ) |
| `pii_residual` | خودآزمایی ناشناس‌سازی |
| `tokenizer_round_trip` | متن پس از encode/decode توکنایزر عیناً برنمی‌گردد |
| `too_many_tokens` | طول گفت‌وگو بیش از `--max-tokens` (۴۰۹۶) |
| `invalid_record` | مقدار نامعتبر در داده‌ی خام (مثلاً عدد غیرعددی در `agent_analysis`)؛ فقط شمرده می‌شود و پیام خطا هیچ‌جا چاپ نمی‌شود |

نرمال‌سازی (text_clean.py): NFC؛ «ي/ى/ك» ← «ی/ک»؛ همه‌ی ارقام فارسی/عربی ← لاتین؛ حذف نویسه‌های کنترلی،
نامرئی (zero-width، LRM/RLM، BOM) به‌جز نیم‌فاصله (U+200C)، U+FFFD، surrogate تنها و Private-Use؛ تعمیر
تکه‌به‌تکه‌ی mojibake (UTF-8 خوانده‌شده با Latin-1/CP1252)؛ یکی کردن فاصله‌ها.

## تقسیم Train / Validation / Test (split.py)

- ۸۰٪ / ۱۰٪ / ۱۰٪، قطعی با `--seed` (پیش‌فرض ۴۲).
- **گروهی:** همه‌ی رکوردهای یک کارجو فقط در یک بخش (جلوگیری از Data Leakage).
- **لایه‌بندی‌شده** بر اساس سطل نمره (0-19، 20-39، 40-59، 60-79، 80-100).
- در هر سطل گروه‌ها پس از بُر خوردن (بزرگ‌ترها اول) به بخشی داده می‌شوند که بیشترین کسری نسبت به سهمش را دارد.

## توکنایزر و طول کانتکست

طول هر رکورد = کل گفت‌وگوی آموزشی در قالب چت ChatML (`system`=instruction، `user`=input، `assistant`=output)
به‌همراه نشانه‌های قالب، با `tokenizer.json` مدل پایه‌ی هدف (کتابخانه‌ی `tokenizers`). مسیر فایل با `--tokenizer`
داده می‌شود و هیچ مدل مشخصی در کد ثابت نیست. همان فایل باید هنگام ساخت و اعتبارسنجی استفاده شود
(اثر انگشتش در `stats.json → tokenizer_sha256` است).

## اعتبارسنج (validate.py)

مستقل از کد ساخت نوشته شده (فقط تابع هش و توکن‌سازی ایندکس کور مشترک است). با هر خطا کد خروج ۱:

| دسته | کدها |
|------|------|
| ساختار | `schema_invalid_utf8`، `schema_invalid_json`، `schema_keys`، `schema_empty_field`، `schema_output_json`، `schema_score_range` |
| هویت | `pii_email`، `pii_phone`، `pii_url`، `pii_handle`، `pii_national_id`، `pii_birth_date`، `pii_address`، `pii_identity` (هش manifest) |
| توکن خراب | `broken_replacement_char`، `broken_control_char`، `broken_surrogate`، `broken_invisible_char`، `broken_mojibake`، `broken_round_trip` |
| کانتکست | `context_overflow` (+ گزارش p95 و max توکن هر بخش) |
| تقسیم | `leakage_group`، `split_ratio` (تلورانس `--ratio-tolerance`، پیش‌فرض ±۱٪)، `manifest_missing`، `manifest_mismatch`، `missing_file` |

گزارش فقط کد خطا، نام فایل و شماره‌ی خط دارد؛ هرگز محتوای رکورد.

## اجرا

### روی سرور Production

```bash
cd /opt/ats-smart
TOKENIZER_URL='<نشانی مستقیم tokenizer.json مدل پایه>' bash deploy/finetune-dataset.sh
# دفعه‌های بعد (توکنایزر در datasets/tokenizer/ مانده):
bash deploy/finetune-dataset.sh --min-pairs 10000
```

خروجی در `/opt/ats-smart/datasets/finetune-<زمان>-<pid>/dataset` (پوشه 700، فایل‌ها 600). اگر اعتبارسنجی رد شود،
پوشه به `dataset.FAILED` تغییر نام می‌دهد و نباید برای آموزش استفاده شود. اگر سرور به نشانی توکنایزر دسترسی
نداشت، اسکریپت دستور `scp` از ویندوز را چاپ می‌کند؛ با `TOKENIZER_SHA256` هش فایل پیش از استفاده بررسی می‌شود.

## بنچمارک لوکال (۱۰ هزار+ جفت)

Docker با `--cpus=2` (هم‌اندازه‌ی CPU سرور)، ۱۱٬۰۰۰ جفت ساختگی seeder، توکنایزر واقعی، `--max-tokens 4096`:

| مرحله | زمان | بیشینه‌ی RAM | نتیجه |
|-------|------|--------------|-------|
| build | ۸۱٫۰ ثانیه | ۱۶۱ مگابایت | ۱۰٬۷۸۹ جفت واجد شرایط ← ۱۰٬۳۱۸ رکورد (train ۸٬۲۵۴ / validation ۱٬۰۳۳ / test ۱٬۰۳۱) |
| validate | ۴۱٫۳ ثانیه | ۱۳۲ مگابایت | pass — بدون هیچ خطای PII، توکن خراب یا سرریز (p95 ≈ ۱٬۳۸۵، max = ۱٬۶۰۹ توکن) |

رکوردهای حذف‌شده: mojibake ۱۰۸، duplicate_exact ۱۰۵، outlier_experience_years ۵۸، too_short ۵۷، too_long ۵۱،
missing_agent_analysis ۵۰، missing_score ۴۲؛ pii_residual صفر.

### لوکال (توسعه)

```bash
python -m app.datasets.finetune.seed --pairs 11000          # فقط غیر Production؛ داده‌ی کاملاً ساختگی
python -m app.datasets.finetune.build --out data/finetune --tokenizer data/tokenizer/tokenizer.json
python -m app.datasets.finetune.validate data/finetune --tokenizer data/tokenizer/tokenizer.json
```

`data/finetune/`، `data/tokenizer/` و `datasets/` در `.gitignore` هستند.
