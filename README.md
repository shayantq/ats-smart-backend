# ATS Smart — Backend

بک‌اند پلتفرم هوشمند جذب و استخدام، مبتنی بر FastAPI (Async).

## راه‌اندازی محیط توسعه

```bash
python -m venv .venv
source .venv/bin/activate  # ویندوز: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# سپس مقادیر واقعی DATABASE_URL، REDIS_URL و SECRET_KEY را در .env تنظیم کنید

uvicorn app.main:app --reload
```

سرور روی آدرس زیر باال می‌آید:
- مستندات Swagger: http://127.0.0.1:8000/docs
- بررسی سلامت: http://127.0.0.1:8000/api/v1/health

## اجرای تست‌ها

```bash
pytest
```

## ساختار پروژه

```
app/
├── api/v1/
│   ├── endpoints/     # اندپوینت‌های هر دامنه (health, auth, jobs, ...)
│   └── api.py         # روتر مرکزی نسخه v1
├── core/
│   └── config.py      # تنظیمات و متغیرهای محیطی
├── db/                 # اتصال دیتابیس (اسپرینت بعدی)
├── models/              # مدل‌های SQLAlchemy (اسپرینت بعدی)
├── schemas/             # اسکیمای Pydantic
├── services/            # منطق تجاری
└── main.py              # نقطه ورود برنامه
```
