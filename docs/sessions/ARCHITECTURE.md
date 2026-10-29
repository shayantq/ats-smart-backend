# مدیریت نشست‌ها (Session Management)

هدف این بخش جلوگیری از ربوده شدن حساب‌ها (به‌خصوص حساب Admin) است. Refresh Token دیگر یک JWT کاملاً Stateless نیست: هر ورود یک **نشست** در Redis می‌سازد، و توکن فقط تا وقتی معتبر است که نشستش زنده باشد. کاربر و Admin سازمان هر نشست را می‌توانند فوراً باطل کنند.

| فایل | نقش |
|---|---|
| `app/core/sessions.py` | چرخه‌ی عمر نشست در Redis، چرخش Refresh Token، ابطال، تشخیص دستگاه جدید و ورود مشکوک |
| `app/core/geoip.py` | موقعیت جغرافیایی IP از فایل mmdb محلی (DB-IP City Lite) و فاصله‌ی Haversine |
| `app/routers/auth.py` | `login` · `refresh` · `logout` · `GET /sessions/` · `DELETE /sessions/{id}/` |
| `app/routers/admin.py` | نشست‌های کارمندان سازمان خود Admin |
| `app/core/deps.py` | هر درخواست احرازشده: نشست `sid` توکن باید هنوز زنده باشد |
| `app/tasks/notifications.py` | ایمیل «ورود از دستگاه جدید» و «Suspicious Login» (Worker صف) |
| `frontend/src/services/apiClient.ts` · `components/security/ActiveSessionsPanel.tsx` | نوسازی خودکار، هدایت به صفحه‌ی ورود، صفحه‌ی نشست‌های فعال |

---

## ۱. کلیدهای Redis

همه‌ی کلیدها TTL دارند، و فهرست‌ها سقف دارند. هیچ کلیدی بی‌حد رشد نمی‌کند.

| کلید | نوع | محتوا | عمر |
|---|---|---|---|
| `session:{sid}` | Hash | `user_id`، `tenant_id`، `ip`، `user_agent`، `browser`/`browser_version`، `os`/`os_version`، `device_type`، `device`، `country_code`/`country`/`city`/`lat`/`lon`، `created_at`، `last_active_at`، `expires_at`، `refresh_jti`، `previous_jti`، `rotated_at`، `suspicious` | عمر Refresh Token (۷ روز)، که با هر نوسازی تمدید می‌شود |
| `user_sessions:{user_id}` | Sorted Set | شناسه‌ی نشست‌ها؛ امتیاز = آخرین فعالیت | عمر Refresh Token؛ ردیف نشست‌های منقضی هنگام فهرست‌گیری حذف می‌شود |
| `revoked_refresh:{jti}` | String | `revoked` (ابطال) یا `rotated` (چرخش) | تا پایان عمر همان توکن |
| `session_touch:{sid}` | String | قفل ثبت آخرین فعالیت | ۶۰ ثانیه |
| `user_known_devices:{user_id}` | Sorted Set | `ua:مرورگر\|سیستم‌عامل` و `ip:نشانی` | ۹۰ روز، حداکثر ۵۰ عضو |
| `user_login_history:{user_id}` | List | ۲۰ ورود اخیر: زمان، IP، کشور، مختصات | ۹۰ روز |

Claim های توکن:

- access_token: `sub`، `tid` و `sid`
- refresh_token: `sub`، `sid` و `jti`

---

## ۲. جریان‌ها

```
ورود ─► create_session: Hash نشست + ایندکس کاربر + اثر انگشت دستگاه + سابقه‌ی ورود (یک تراکنش MULTI)
     └► assess_login ─► ایمیل هشدار در صف notifications (RQ)، بدون معطل کردن پاسخ ورود
         access_token(sid) + refresh_token(sid, jti) در کوکی HttpOnly

هر درخواست ─► get_current_user ─► touch_session: HGET + SET NX در یک رفت‌وبرگشت
                                  نشست نیست ← 401 · Redis قطع ← 503 (Fail Closed)

نوسازی ─► rotate_refresh (WATCH/MULTI):
           jti == refresh_jti            ← jti تازه، jti قبلی ← revoked_refresh (rotated)، کوکی تازه
           jti == previous_jti و ≤ ۱۰ ثانیه ← فقط access_token (تب دیگر همان مرورگر، هم‌زمان)
           غیر از این                     ← استفاده‌ی دوباره (Replay) ← کل نشست باطل ← 401
           نشست نیست / کاربر دیگر / توکن بدون sid ← 401 و پاک شدن کوکی

ابطال (کاربر یا Admin) ─► revoke_session: jti فعلی ← revoked_refresh (revoked)، حذف Hash و ایندکس
     دستگاه باطل‌شده: درخواست بعدی ← 401، نوسازی ← 401 ← فرانت‌اند به صفحه‌ی ورود می‌برد
```

- **IP واقعی کاربر:** زنجیره‌ی `Caddy ← Gateway (real_ip از Proxy مورد اعتماد) ← uvicorn --proxy-headers` است. API همان IP را می‌بیند که Rate Limiter می‌بیند (`get_remote_address`)، و هدر `X-Forwarded-For` جعلی از اینترنت اثری ندارد.
- **چرخش اتمیک:** دو نوسازی هم‌زمان با یک توکن هر دو برنده نمی‌شوند (WATCH). دومی در بازه‌ی Grace فقط access_token می‌گیرد، چون کوکی مشترک را اولی عوض کرده است.
- **فرانت‌اند:** چند درخواستی که هم‌زمان 401 گرفته‌اند فقط یک نوسازی مشترک انجام می‌دهند. اگر نوسازی ناموفق باشد، توکن پاک و رویداد `ats:unauthorized` پخش می‌شود و کاربر به صفحه‌ی ورود برمی‌گردد. خروج هم نشست سمت سرور را باطل می‌کند. لینک ایمیل هشدار (`/?view=sessions`) مستقیم صفحه‌ی «نشست‌های فعال» را باز می‌کند.

---

## ۳. تشخیص دستگاه جدید و ورود مشکوک

**دستگاه جدید:** اثر انگشت `مرورگر|سیستم‌عامل` (نه نسخه، تا به‌روزرسانی مرورگر هشدار نسازد) یا IP در `user_known_devices` نیست. نتیجه، ایمیل «ورود به حساب شما از دستگاه جدید» است. اولین ورود (بدون هیچ سابقه‌ای) هشدار ندارد.

**ورود مشکوک** (`detect_anomaly`)، با موقعیت IP از دیتابیس محلی:

1. **کشور تازه:** کشور ورود با هیچ‌کدام از کشورهای ۲۰ ورود اخیر یکی نیست.
2. **جابه‌جایی ناممکن:** فاصله‌ی Haversine از آخرین ورودِ دارای مختصات بیش از `SUSPICIOUS_LOGIN_DISTANCE_KM` (۵۰۰) **و** سرعت لازم برای طی آن بیش از `SUSPICIOUS_LOGIN_SPEED_KMH` (۹۰۰ کیلومتر بر ساعت، حدود سرعت هواپیما). حداقل فاصله‌ی زمانی برای این محاسبه یک دقیقه در نظر گرفته می‌شود.

هر کدام از این دو قاعده برقرار باشد، ایمیل «⚠️ ورود مشکوک» با دلایل قابل‌فهم ارسال می‌شود (به‌جای ایمیل دستگاه جدید)، و نشست در فهرست با `suspicious=true` علامت می‌خورد.

| نمونه | نتیجه |
|---|---|
| تهران ← آلمان، ۳۰ دقیقه بعد | مشکوک (کشور تازه + حدود ۳۵۰۰ کیلومتر با سرعت حدود ۷۰۰۰ کیلومتر بر ساعت) |
| تهران ← مشهد، ۳۰ دقیقه بعد | مشکوک (حدود ۷۴۰ کیلومتر با سرعت حدود ۱۵۰۰ کیلومتر بر ساعت) |
| تهران ← مشهد، ۵ ساعت بعد | عادی (پرواز داخلی) |
| تهران ← کرج، ۱ دقیقه بعد | عادی (حدود ۴۰ کیلومتر، زیر آستانه) |
| IP خصوصی، یا نبود دیتابیس GeoIP | قواعد جغرافیایی اعمال نمی‌شوند؛ ورود هرگز به‌خاطرش شکست نمی‌خورد |

**دیتابیس GeoIP:**

- **منبع:** DB-IP City Lite (رایگان، بدون کلید، مجوز CC BY 4.0، https://db-ip.com).
- **دانلود:** `deploy/geoip-update.sh` بعد از هر استقرار در پس‌زمینه اجرا می‌شود؛ اگر فایل جدیدتر از ۳۵ روز باشد کاری نمی‌کند.
- **مسیر:** فایل در `/opt/ats-smart/geoip/` قرار می‌گیرد و به‌صورت پوشه، فقط‌خواندنی، در `/srv/geoip` کانتینر Mount می‌شود.
- **حافظه:** فایل با mmap خوانده می‌شود؛ فقط صفحه‌های لازم در RAM می‌مانند. هر جستجو زیر ۱ میلی‌ثانیه طول می‌کشد.
- **حریم خصوصی:** هیچ IP ای به سرویس بیرونی فرستاده نمی‌شود.
- **بدون ری‌استارت:** اگر فایل هنوز نیامده باشد، API هر ۱۰ دقیقه دوباره امتحان می‌کند.

---

## ۴. API

| مسیر | دسترسی | پاسخ |
|---|---|---|
| `POST /api/v1/auth/login` | عمومی | توکن‌ها + کوکی · Redis قطع ← `503` |
| `POST /api/v1/auth/refresh` | کوکی یا `{refresh_token}` | `{access_token, refresh_token\|null, expires_in}` · باطل ← `401` و پاک شدن کوکی |
| `GET /api/v1/auth/sessions/` | کاربر | `{items: [{id, browser, browser_version, os, os_version, device_type, device, user_agent, ip, location, created_at, last_active_at, expires_at, is_current, suspicious}]}` |
| `DELETE /api/v1/auth/sessions/{id}/` | کاربر | `204` · نشست کاربر دیگر ← `404` |
| `POST /api/v1/auth/logout` | کاربر | `204` و پاک شدن کوکی |
| `GET /api/v1/admin/users/{id}/sessions/` | Admin | نشست‌های کارمند سازمان خود، با IP کامل |
| `DELETE /api/v1/admin/users/{id}/sessions/{sid}/` · `DELETE …/sessions/` | Admin | ابطال یک نشست / همه (`{revoked: n}`) · سازمان دیگر ← `404` |

---

## ۵. راستی‌آزمایی

```bash
pytest tests/unit/test_sessions.py tests/integration/test_sessions_api.py
cd frontend && npx jest src/App.test.tsx src/components/security
cd /opt/ats-smart && bash deploy/session-check.sh        # روی سرور ← [SESSIONS PASS]
```

| معیار پذیرش | اثبات |
|---|---|
| ابطال نشست ← jti در فهرست سیاه Redis، نوسازی ← `401`، فرانت‌اند ← صفحه‌ی ورود | `test_revoked_session_cannot_refresh_and_is_sent_to_login` · `App.test.tsx` · بخش ۲ اسکریپت سرور |
| فهرست نشست‌ها با جزئیات مرورگر و آخرین فعالیت | `test_sessions_list_shows_browser_details_and_last_activity` · بخش ۱ اسکریپت سرور |
| ورود از مرورگر/IP تازه ← کار ایمیل در صف Redis؛ کشور دور ← «Suspicious Login» | `test_login_from_new_browser_or_ip_enqueues_security_email` و `…_suspicious_login_email` روی صف واقعی RQ · بخش ۳ و ۴ اسکریپت سرور |

---

## ۶. محدودیت‌ها و تصمیم‌ها

- **Redis وابستگی حیاتی احراز هویت شد:** اگر Redis قطع باشد، ورود و درخواست‌های احرازشده `503` می‌گیرند (Fail Closed). پذیرفتن نشستی که ممکن است باطل شده باشد خطرناک‌تر است. Redis با AOF پایدار است، پس ری‌استارتش نشست‌ها را پاک نمی‌کند.
- **کاربران فعلی یک‌بار دوباره وارد می‌شوند:** توکن‌های صادرشده پیش از این استقرار `sid` ندارند و با `401` رد می‌شوند.
- **دقت موقعیت IP:** دقت در حد شهر است و VPN یا Proxy آن را جابه‌جا می‌کند. کاربری که با VPN وارد شود ممکن است هشدار «ورود مشکوک» بگیرد. این فقط هشدار است و ورود مسدود نمی‌شود.
- **آستانه‌ی ۹۰ روز:** کاربری که ۹۰ روز وارد نشده باشد، در ورود بعدی مثل «اولین ورود» بدون هشدار حساب می‌شود.
- **تغییر رمز عبور** (`/reset-password`) هنوز نشست‌های دیگر را خودکار باطل نمی‌کند. این قدم بعدی پیشنهادی است و بیرون از محدوده‌ی این تسک ماند.
- **ارسال واقعی ایمیل** به تنظیم `SMTP_*` روی سرور وابسته است. تا آن موقع کار ایمیل در صف ثبت می‌شود و پس از سه تلاش مجدد در `FailedJobRegistry` می‌ماند.
