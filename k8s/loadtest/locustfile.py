"""
تست بار کوتاه برای سنجش HPA و توزیع بار Ingress — سناریوی «انتشار یک آگهی پرطرفدار».

هزاران کارجو هم‌زمان سایت را باز می‌کنند و مدام فهرست آگهی‌ها را مرور می‌کنند (پرتکرارترین
درخواست سیستم در اوج ترافیک). همه‌ی درخواست‌ها از مسیر واقعی کاربر عبور می‌کنند:
    Locust ─► Service ورودی NGINX Ingress ─► Pod های backend-api / frontend ─► PostgreSQL

اجرا داخل کلاستر به‌صورت Job (k8s/hpa-stress.sh). شکل بار (LoadShape):
    ۱. افزایش تدریجی تا LOAD_USERS کاربر در LOAD_RAMP ثانیه
    ۲. نگه‌داشتن اوج به مدت LOAD_HOLD ثانیه   ← HPA باید Pod اضافه کند
    ۳. توقف کامل                               ← HPA باید Pod های اضافه را کم کند

خروجی پایانی: تعداد پاسخ‌ها به تفکیک کد وضعیت + خط [NO-5XX PASS/FAIL] (معیار «بدون خطای 502»).

رفتار مثل مرورگر: NGINX متن‌باز با هر افزوده/حذف شدن Pod پیکربندی را Reload می‌کند و اتصال‌های
keep-alive بی‌کار را می‌بندد. مرورگرها (طبق RFC 9112 بخش 9.3.1) درخواست idempotent (GET) را که روی
چنین اتصالی قطع شود خودکار روی اتصال تازه تکرار می‌کنند و کاربر چیزی نمی‌بیند؛ python-requests این کار
را نمی‌کند. اینجا همان یک تکرار — فقط GET و فقط برای قطع اتصال، نه پاسخ خطای سرور — شبیه‌سازی و
تعدادش جدا گزارش می‌شود (STALE_CONNECTION_RETRIES).
"""

import os
from collections import Counter

from locust import HttpUser, LoadTestShape, between, events, task
from urllib3.util.retry import Retry

USERS = int(os.environ.get("LOAD_USERS", "150"))
RAMP = int(os.environ.get("LOAD_RAMP", "60"))
HOLD = int(os.environ.get("LOAD_HOLD", "180"))
HOST_HEADER = os.environ.get("LOAD_HOST_HEADER", "localhost")

status_counts: Counter = Counter()
stale_connection_retries = 0


class BrowserLikeRetry(Retry):
    """یک تکرار GET روی اتصال keep-alive بسته‌شده — پاسخ‌های HTTP (حتی 5xx) هرگز تکرار نمی‌شوند."""

    def increment(self, *args, **kwargs):
        global stale_connection_retries
        stale_connection_retries += 1
        return super().increment(*args, **kwargs)


@events.request.add_listener
def _count_status(response=None, exception=None, **_kwargs):
    if response is not None and getattr(response, "status_code", 0):
        status_counts[response.status_code] += 1
    else:
        status_counts["connection-error"] += 1


@events.quitting.add_listener
def _report(environment, **_kwargs):
    total = sum(status_counts.values())
    server_errors = sum(count for code, count in status_counts.items() if isinstance(code, int) and code >= 500)
    errors = server_errors + status_counts["connection-error"]
    print("STATUS_CODES " + " ".join(f"{code}={count}" for code, count in sorted(status_counts.items(), key=str)))
    print(f"TOTAL_REQUESTS {total}")
    print(f"BAD_GATEWAY_502 {status_counts[502]}")
    print(f"STALE_CONNECTION_RETRIES {stale_connection_retries}")
    verdict = "PASS" if total > 0 and errors == 0 else "FAIL"
    print(f"[NO-5XX {verdict}] {total} درخواست، {errors} خطای سرور/اتصال (502: {status_counts[502]})")
    environment.process_exit_code = 0 if verdict == "PASS" else 1


class JobSeeker(HttpUser):
    # «زمان فکر کردن» کوتاه = سناریوی استرس (کاربر واقعی هر چند ثانیه کلیک می‌کند)
    wait_time = between(0.2, 1.0)

    def on_start(self) -> None:
        # Ingress بر اساس نام دامنه مسیریابی می‌کند (k8s/base/ingress.yaml)
        self.client.headers["Host"] = HOST_HEADER
        retry = BrowserLikeRetry(total=1, connect=1, read=1, status=0, allowed_methods={"GET"}, raise_on_status=False)
        for adapter in self.client.adapters.values():
            adapter.max_retries = retry

    @task(6)
    def browse_jobs(self) -> None:
        self.client.get("/api/v1/jobs/?limit=50", name="/api/v1/jobs/")

    @task(2)
    def browse_active_jobs(self) -> None:
        self.client.get("/api/v1/jobs/?status=Active&limit=20", name="/api/v1/jobs/?status=Active")

    @task(1)
    def open_site(self) -> None:
        self.client.get("/", name="/ (frontend)")

    @task(1)
    def health(self) -> None:
        self.client.get("/api/v1/health/ready", name="/api/v1/health/ready")


class RampHoldStop(LoadTestShape):
    def tick(self):
        elapsed = self.get_run_time()
        if elapsed < RAMP:
            users = max(1, int(USERS * elapsed / RAMP))
            return users, max(1, USERS // max(RAMP // 4, 1))
        if elapsed < RAMP + HOLD:
            return USERS, USERS
        return None
