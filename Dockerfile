# =============================================================================
# ایمیج بک‌اند ATS Smart (FastAPI) — معماری چندمرحله‌ای (Multi-stage Build)
#
#   مرحله‌ی ۱ (builder):    ابزارهای کامپایل + نصب تمام وابستگی‌ها در یک venv ایزوله
#   مرحله‌ی ۲ (production): فقط venv آماده + کد برنامه + کتابخانه‌های سیستمی زمان اجرا
#
# هیچ‌کدام از ابزارهای کامپایل (gcc، هدرهای توسعه، کش pip) وارد ایمیج نهایی
# نمی‌شوند. همین یک ایمیج برای API، Worker صف، rq-scheduler و اجرای مایگریشن‌ها
# استفاده می‌شود (فقط command کانتینر فرق دارد — بنگرید docker-compose.yml).
#
# بیلد:   docker build -t ats-smart-backend .
# اجرا:   docker run --rm -p 8000:8000 --env-file .env ats-smart-backend
# =============================================================================

ARG PYTHON_IMAGE=python:3.11-slim
# اختیاری: آدرس جایگزین مخزن‌های Debian (scheme + host) برای شبکه‌هایی که دانلود
# HTTP ساده در آن‌ها وسط کار قطع می‌شود. معمولاً همان مخزن رسمی ولی با HTTPS کافی است:
#   --build-arg DEBIAN_MIRROR=https://deb.debian.org
# خالی (پیش‌فرض، از جمله در CI) = بدون تغییر

ARG DEBIAN_MIRROR=""

# -----------------------------------------------------------------------------
# مرحله‌ی ۱: Build Stage
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

ARG DEBIAN_MIRROR
# مقاوم‌سازی apt در برابر شبکه‌ی ناپایدار: تلاش مجدد + خاموش‌کردن HTTP Pipelining
# (قطع‌شدن اتصال وسط دانلود بسته‌ها با خطای «unexpected EOF» را برطرف می‌کند)
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/99-network-resilience \
    && echo 'Acquire::http::Pipeline-Depth "0";' >> /etc/apt/apt.conf.d/99-network-resilience \
    && if [ -n "${DEBIAN_MIRROR}" ]; then \
        sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi

# ابزارهای پایه‌ی کامپایل — برای پکیج‌هایی که روی این پلتفرم wheel آماده ندارند
# و باید از سورس کامپایل شوند. فقط در همین مرحله وجود دارند.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# venv جدا تا مرحله‌ی بعد بتواند «فقط» وابستگی‌های نصب‌شده را با یک COPY بردارد
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# اول فقط requirements کپی می‌شود تا تغییر کد برنامه، کش لایه‌ی نصب وابستگی‌ها را باطل نکند
COPY requirements.txt .
RUN pip install --upgrade pip wheel \
    && pip install -r requirements.txt

# مدل زبانی spaCy برای NER رزومه (app/core/resume_parser.py). با
# --build-arg SPACY_MODEL_URL= (خالی) می‌توان آن را حذف کرد؛ ماژول بدون مدل هم
# فقط با قواعد Regex کار می‌کند.
ARG SPACY_MODEL_URL=https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
RUN if [ -n "${SPACY_MODEL_URL}" ]; then pip install "${SPACY_MODEL_URL}"; fi

# کوچک‌سازی: حذف فایل‌های کامپایل‌شده‌ی پایتون و پوشه‌ی تست‌های داخلی پکیج‌ها
# (هیچ‌کدام در زمان اجرا لازم نیستند)
RUN find /opt/venv -type d -name "__pycache__" -prune -exec rm -rf {} + \
    && find /opt/venv/lib -type d -path "*/site-packages/*/tests" -prune -exec rm -rf {} +

# -----------------------------------------------------------------------------
# مرحله‌ی ۲: Production Stage
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS production

LABEL org.opencontainers.image.title="ats-smart-backend" \
      org.opencontainers.image.description="ATS Smart — FastAPI backend, RQ worker & scheduler"

# PYTHONDONTWRITEBYTECODE: فایل‌های .pyc روی دیسک کانتینر نوشته نمی‌شوند
# PYTHONUNBUFFERED:        لاگ‌ها بدون بافر و بلافاصله به stdout می‌روند (docker logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    MEDIA_ROOT=/app/media

ARG DEBIAN_MIRROR
# مقاوم‌سازی apt در برابر شبکه‌ی ناپایدار: تلاش مجدد + خاموش‌کردن HTTP Pipelining
# (قطع‌شدن اتصال وسط دانلود بسته‌ها با خطای «unexpected EOF» را برطرف می‌کند)
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/99-network-resilience \
    && echo 'Acquire::http::Pipeline-Depth "0";' >> /etc/apt/apt.conf.d/99-network-resilience \
    && if [ -n "${DEBIAN_MIRROR}" ]; then \
        sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi

# فقط کتابخانه‌های سیستمی «زمان اجرا»: موتور OCR (Tesseract) + داده‌ی زبان فارسی
# برای رزومه‌های اسکن‌شده (app/core/text_extraction.py). انگلیسی پیش‌فرض نصب است.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-fas \
    && rm -rf /var/lib/apt/lists/*

# اجرای برنامه با کاربر غیر root (کمترین سطح دسترسی)
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
# کد برنامه متعلق به root و برای کاربر app فقط‌خواندنی است؛ فقط media قابل نوشتن است
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN mkdir -p /app/media && chown app:app /app/media

USER app

EXPOSE 8000

# بدون curl (برای سبک ماندن ایمیج) — با خودِ پایتون. استقرار بدون قطعی
# (deploy/deploy.sh) دقیقاً منتظر همین وضعیت healthy می‌ماند.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]

# یک پردازه‌ی uvicorn در هر کانتینر (مقیاس‌پذیری = تعداد کانتینرها؛ بنگرید
# app/core/metrics.py). روی SIGTERM درخواست‌های در حال اجرا تا ۳۰ ثانیه تمام می‌شوند.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "30"]
