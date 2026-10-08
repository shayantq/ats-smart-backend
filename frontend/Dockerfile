# =============================================================================
# ایمیج فرانت‌اند ATS Smart (React + Vite) — چندمرحله‌ای
#
#   مرحله‌ی ۱ (build):      Node.js — نصب وابستگی‌ها و تولید فایل‌های استاتیک (dist)
#   مرحله‌ی ۲ (production): فقط Nginx + فایل‌های استاتیک؛ Node.js و node_modules
#                           اصلاً وارد ایمیج نهایی نمی‌شوند.
#
# Nginx علاوه بر سرو فایل‌های استاتیک، مسیرهای /api و /media را به سرویس
# بک‌اند پراکسی می‌کند (nginx.conf) — مرورگر فقط با یک Origin صحبت می‌کند.
# =============================================================================

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

# آدرس API در زمان «بیلد» داخل باندل جاوااسکریپت قرار می‌گیرد (رفتار Vite).
# مسیر نسبی /api/v1 یعنی «همان دامنه‌ای که سایت از آن باز شده» — Nginx همین
# ایمیج آن را به بک‌اند می‌رساند، پس ایمیج به دامنه‌ی خاصی وابسته نیست.
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

# -----------------------------------------------------------------------------
FROM nginx:1.27-alpine AS production

# ایمیج رسمی nginx فایل‌های /etc/nginx/templates/*.template را هنگام شروع
# کانتینر با envsubst به conf.d تبدیل می‌کند (فقط متغیرهای تعریف‌شده‌ی زیر
# جایگزین می‌شوند؛ متغیرهای خودِ nginx مثل $uri دست‌نخورده می‌مانند).
ENV BACKEND_UPSTREAM=backend_api:8000 \
    NGINX_RESOLVER=127.0.0.11

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
