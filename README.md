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
- `refresh_token`: طول عمر بلند (پیش‌فرض ۷ روز)، هم در بدنه‌ی پاسخ و هم در یک کوکی `HttpOnly` + `Secure` قرار می‌گیرد

⚠️ نکته: چون کوکی با پرچم `Secure` تنظیم شده، مرورگر فقط آن را روی یک "Secure Context" ذخیره می‌کند. آدرس `http://localhost:8000/docs` این شرط را دارد، ولی `http://127.0.0.1:8000/docs` **ندارد** — برای دیدن کوکی در مرورگر حتماً از `localhost` استفاده کنید، نه `127.0.0.1`.

## کنترل دسترسی بر اساس نقش (RBAC)

مسیرهای حساس با `Depends(require_roles("Admin"))` (یا هر نقش دیگری) محافظت می‌شوند:
- بدون توکن یا با توکن نامعتبر/منقضی → کد `401`
- با توکن معتبر ولی نقش غیرمجاز → کد `403`

### نمونه‌ی محافظت‌شده برای تست
```
GET /api/v1/admin/stats
```
فقط برای نقش `Admin`. برای فراخوانی، در Swagger روی دکمه‌ی 🔒 **Authorize** بالای صفحه بزنید و `access_token` گرفته‌شده از مسیر `/login` را وارد کنید (بدون کلمه‌ی `Bearer`، خودِ Swagger اضافه‌اش می‌کند).

## ساختار کلی ریپو

```
ats-smart-backend/            # ریشه‌ی ریپو
├── app/                       # بک‌اند
│   ├── routers/                # اندپوینت‌ها (health, auth, admin, و در آینده jobs, ...)
│   ├── core/
│   │   ├── config.py             # تنظیمات و متغیرهای محیطی
│   │   ├── security.py            # هش کردن گذرواژه (Bcrypt) و صدور/رمزگشایی توکن‌های JWT
│   │   └── deps.py                # لایه‌ی RBAC: get_current_user و require_roles
│   ├── db/
│   │   └── session.py             # اتصال async به دیتابیس
│   ├── models/                  # مدل‌های ORM (SQLAlchemy) — 14 جدول طراحی دیتابیس
│   │   ├── base.py
│   │   ├── core.py               # User, Company, Candidate, Job
│   │   ├── process.py            # Application, Interview, Resume, Skill
│   │   └── security.py           # Role, Permission, Notification, Log, Audit, StatusHistory
│   ├── schemas/                  # اسکیمای Pydantic (auth.py, health.py, ...)
│   └── main.py                    # نقطه ورود برنامه
├── alembic/                    # مدیریت نسخه‌بندی دیتابیس
├── tests/                       # تست‌های بک‌اند
├── frontend/                    # فرانت‌اند (React + TypeScript + Tailwind)
├── requirements.txt
└── alembic.ini
```
