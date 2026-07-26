# ATS Smart — Backend

بک‌اند پلتفرم هوشمند جذب و استخدام، مبتنی بر FastAPI (Async).

## راه‌اندازی محیط توسعه

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

## ساختار پروژه

```
app/
├── routers/            # اندپوینت‌های هر دامنه (health, و در آینده auth, jobs, ...)
│   └── health.py
├── core/
│   └── config.py        # تنظیمات و متغیرهای محیطی (خوانده‌شده از .env)
├── models/               # مدل‌های ORM (SQLAlchemy) — معادل ۱۴ جدول طراحی دیتابیس
│   ├── base.py           # کلاس پایه‌ی مشترک همه‌ی مدل‌ها
│   ├── core.py           # User, Company, Candidate, Job
│   ├── process.py        # Application, Interview, Resume, Skill
│   └── security.py       # Role, Permission, Notification, Log, Audit, StatusHistory
├── schemas/              # اسکیمای Pydantic
└── main.py               # نقطه ورود برنامه
alembic/
├── env.py                # پیکربندی اتصال Alembic به مدل‌ها و دیتابیس
├── script.py.mako        # قالب فایل‌های migration
└── versions/              # فایل‌های migration تولیدشده
tests/
└── test_health.py        # تست اندپوینت health
```
