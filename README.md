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

## ساختار کلی ریپو

```
ats-smart-backend/            # ریشه‌ی ریپو
├── app/                       # بک‌اند
│   ├── routers/                # اندپوینت‌ها (health, و در آینده auth, jobs, ...)
│   ├── core/
│   │   └── config.py            # تنظیمات و متغیرهای محیطی
│   ├── models/                  # مدل‌های ORM (SQLAlchemy) — 14 جدول طراحی دیتابیس
│   │   ├── base.py
│   │   ├── core.py               # User, Company, Candidate, Job
│   │   ├── process.py            # Application, Interview, Resume, Skill
│   │   └── security.py           # Role, Permission, Notification, Log, Audit, StatusHistory
│   ├── schemas/                  # اسکیمای Pydantic
│   └── main.py                    # نقطه ورود برنامه
├── alembic/                    # مدیریت نسخه‌بندی دیتابیس
├── tests/                       # تست‌های بک‌اند
├── frontend/                    # فرانت‌اند (React + TypeScript + Tailwind)
├── requirements.txt
└── alembic.ini
```
