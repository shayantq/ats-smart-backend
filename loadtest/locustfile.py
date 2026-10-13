"""
تست بار ATS Smart با Locust — سناریوی «باز شدن یک پوزیشن بزرگ»: هزاران کارجو هم‌زمان وارد
سایت می‌شوند، رزومه‌شان را آپلود می‌کنند و بعد مدام آگهی‌ها و وضعیت درخواستشان را چک می‌کنند.

هر کاربر مجازی Locust = یک کارجوی واقعی با حساب یکتای خودش (seed_loadtest_data.py):
    ۱. ورود  (POST /api/v1/auth/login)                 — یک بار، با Bcrypt واقعی
    ۲. آپلود رزومه (POST /api/v1/resumes/upload)        — یک بار، PDF واقعی
    ۳. مرور تکراری: لیست آگهی‌ها، رهگیر وضعیت، پروفایل  — با مکث «زمان فکر کردن» بین کارها

همه‌ی درخواست‌ها از مسیر واقعی کاربر عبور می‌کنند: Nginx فرانت‌اند ← بک‌اند ← PostgreSQL/Redis.
هر کاربر مجازی IP جدای خودش را دارد (هدر X-Forwarded-For) تا Rate Limit واقعی سرور (۵ ورود در
دقیقه برای هر IP) روشن بماند و درست مثل دنیای واقعی، روی هر کاربر جدا اعمال شود.

متغیرهای محیطی:
    LOADTEST_ACCOUNTS   تعداد حساب‌های seed‌شده (پیش‌فرض ۵۰۰۰)
    LOADTEST_PASSWORD   رمز مشترک حساب‌ها (همان seed_loadtest_data.py)
    LOADTEST_MIN_WAIT / LOADTEST_MAX_WAIT
                        «زمان فکر کردن» کاربر بین دو کلیک، به ثانیه (پیش‌فرض ۵ تا ۱۵).
                        این عدد تعیین می‌کند «N کاربر هم‌زمان» یعنی چند درخواست در ثانیه:
                        RPS ≈ N / (میانگین زمان فکر + زمان پاسخ). کاربر واقعی آگهی‌ها را
                        می‌خواند و هر ۵ تا ۱۵ ثانیه کلیک می‌کند؛ ۱ تا ۵ ثانیه یک سناریوی
                        «استرس» بسیار سخت‌گیرانه است (۳ برابر درخواست بیشتر با همان تعداد کاربر).
"""

import itertools
import os
from pathlib import Path

from locust import HttpUser, between, events, task
from locust.runners import WorkerRunner

ACCOUNT_COUNT = int(os.environ.get("LOADTEST_ACCOUNTS", "5000"))
MIN_WAIT = float(os.environ.get("LOADTEST_MIN_WAIT", "5"))
MAX_WAIT = float(os.environ.get("LOADTEST_MAX_WAIT", "15"))
PASSWORD = os.environ.get("LOADTEST_PASSWORD", "LoadTest!2026")
RESUME_PDF = (Path(__file__).parent / "sample_resume.pdf").read_bytes()

# هر Worker بازه‌ی جدای حساب‌ها را برمی‌دارد تا دو کاربر مجازی هرگز با یک حساب وارد نشوند
_account_counter = itertools.count()
_job_id: str | None = None


def _next_account_index(environment) -> int:
    runner = environment.runner
    worker_index = getattr(runner, "worker_index", 0) or 0
    worker_count = max(int(os.environ.get("LOADTEST_WORKERS", "1")), 1)
    return (next(_account_counter) * worker_count + worker_index) % ACCOUNT_COUNT


def _fake_client_ip(index: int) -> str:
    return f"10.{(index >> 16) & 255}.{(index >> 8) & 255}.{index & 255}"


class Candidate(HttpUser):
    wait_time = between(MIN_WAIT, MAX_WAIT)

    def on_start(self) -> None:
        index = _next_account_index(self.environment)
        self.client.headers["X-Forwarded-For"] = _fake_client_ip(index)

        with self.client.post(
            "/api/v1/auth/login",
            json={"email": f"loadtest-candidate-{index}@example.com", "password": PASSWORD},
            name="POST /auth/login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"ورود ناموفق: {response.status_code}")
                self.stop()
                return
            self.client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

        self.upload_resume()

    def upload_resume(self) -> None:
        job_id = self.active_job_id()
        if job_id is None:
            return
        self.client.post(
            "/api/v1/resumes/upload",
            data={"job_id": job_id},
            files={"file": ("resume.pdf", RESUME_PDF, "application/pdf")},
            name="POST /resumes/upload",
        )

    def active_job_id(self) -> str | None:
        global _job_id
        if _job_id is None:
            response = self.client.get("/api/v1/jobs/", params={"status": "Active"}, name="GET /jobs (bootstrap)")
            for job in response.json().get("items", []) if response.ok else []:
                if job["title"].startswith("Load Test"):
                    _job_id = job["job_id"]
                    break
        return _job_id

    @task(5)
    def browse_jobs(self) -> None:
        self.client.get("/api/v1/jobs/", params={"status": "Active", "limit": 20}, name="GET /jobs")

    @task(3)
    def track_my_applications(self) -> None:
        self.client.get("/api/v1/candidates/me/applications", name="GET /candidates/me/applications")

    @task(2)
    def view_profile(self) -> None:
        self.client.get("/api/v1/candidates/me", name="GET /candidates/me")


@events.quitting.add_listener
def _report_acceptance(environment, **_):
    """
    خلاصه‌ی معیارهای پذیرش در پایان اجرا (فقط روی Master که آمار تجمیعی همه‌ی Workerها را دارد):
    p95 زمان پاسخ باید زیر ۲ ثانیه باشد و حتی یک خطای 502/504 هم مردود است.
    """
    if isinstance(environment.runner, WorkerRunner):
        return
    stats = environment.stats.total
    if stats.num_requests == 0:
        return
    p95 = stats.get_response_time_percentile(0.95)
    gateway_errors = sum(
        error.occurrences
        for error in environment.stats.errors.values()
        if any(code in str(error.error) for code in ("502", "504"))
    )
    verdict = "PASS" if p95 < 2000 and gateway_errors == 0 else "FAIL"
    print(
        f"\n[ACCEPTANCE {verdict}] requests={stats.num_requests} failures={stats.num_failures} "
        f"p50={stats.median_response_time:.0f}ms p95={p95:.0f}ms p99={stats.get_response_time_percentile(0.99):.0f}ms "
        f"max={stats.max_response_time:.0f}ms rps={stats.total_rps:.0f} 502/504={gateway_errors}"
    )
    if verdict == "FAIL":
        environment.process_exit_code = 1
