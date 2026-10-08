"""
متریک‌های Prometheus بک‌اند — روی مسیر GET /metrics (بیرون از /api/v1).

دو منبع متریک:
۱. PrometheusMiddleware (یک ASGI Middleware خالص): برای هر درخواست HTTP تعداد،
   زمان پاسخ و کد وضعیت را ثبت می‌کند — پایه‌ی داشبورد RPS/Latency در Grafana و
   هشدار «نرخ خطای سرور بالای ۵٪» (monitoring/prometheus/alerts.yml).
۲. RQQueueCollector: در لحظه‌ی هر Scrape، وضعیت صف کارهای پس‌زمینه‌ی RQ
   (منتظر/در حال اجرا/شکست‌خورده/یادآورهای زمان‌بندی‌شده) و تعداد Workerها را
   مستقیم از Redis می‌خواند.

⚠️ تصمیم مهندسی مستند: کتابخانه‌ی prometheus_client به‌طور پیش‌فرض متریک‌ها را
در حافظه‌ی همان پردازه نگه می‌دارد؛ به همین دلیل هر کانتینر بک‌اند فقط یک
پردازه‌ی uvicorn اجرا می‌کند (بنگرید Dockerfile) و مقیاس‌پذیری افقی با تعداد
کانتینرها انجام می‌شود — Prometheus هر کانتینر را جداگانه (DNS Service Discovery)
Scrape و جمع می‌کند. این از پیچیدگی حالت multiprocess کتابخانه جلوگیری می‌کند.

برچسب route همیشه «الگوی مسیر» است (مثلاً /api/v1/jobs/{job_id})، نه مسیر واقعی
با شناسه‌ها — وگرنه هر UUID یک سری زمانی جدید می‌ساخت (انفجار Cardinality).
"""

import logging
import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Gauge, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

logger = logging.getLogger("ats_smart.metrics")

METRICS_PATH = "/metrics"

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "تعداد کل درخواست‌های HTTP پاسخ‌داده‌شده",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "زمان پاسخ درخواست‌های HTTP (ثانیه)",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "تعداد درخواست‌های HTTP در حال پردازش",
)


def _route_label(scope: Scope) -> str:
    # FastAPI بعد از مسیریابی، شیء route منطبق را داخل همان scope قرار می‌دهد
    route = scope.get("route")
    path_format = getattr(route, "path_format", None) or getattr(route, "path", None)
    if path_format:
        return path_format
    if scope.get("path", "").startswith("/media"):
        return "/media"  # فایل‌های استاتیک mount‌شده (app/main.py) route از نوع APIRoute ندارند
    return "unmatched"  # 404 ها — همه در یک برچسب، نه یک برچسب به‌ازای هر مسیر ناموجود


class PrometheusMiddleware:
    """
    ASGI Middleware خالص (نه BaseHTTPMiddleware، که بدنه‌ی پاسخ را بافر می‌کند).
    اگر لایه‌های داخلی یک Exception مدیریت‌نشده پرتاب کنند، درخواست با کد 500
    شمرده می‌شود — دقیقاً همان پاسخی که ServerErrorMiddleware به کاربر می‌دهد.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == METRICS_PATH:
            await self.app(scope, receive, send)
            return

        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        HTTP_REQUESTS_IN_PROGRESS.inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            HTTP_REQUESTS_IN_PROGRESS.dec()
            method = scope["method"]
            route = _route_label(scope)
            HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status=str(status_code)).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(elapsed)


class RQQueueCollector(Collector):
    """
    وضعیت لحظه‌ای صف RQ در هر Scrape. اتصال Redis جدا و با Timeout کوتاه ساخته
    می‌شود تا قطعی Redis هیچ‌وقت خودِ Scrape را معطل نکند — در آن حالت فقط
    ats_rq_redis_up=0 گزارش می‌شود (که خودش یک هشدار است).
    """

    _QUEUE_NAME = "default"

    def __init__(self) -> None:
        self._connection = None

    def describe(self):
        # بدون این متد، REGISTRY.register برای کشف نام متریک‌ها یک بار collect() را
        # همان لحظه‌ی import صدا می‌زد — یعنی بالا آمدن سرور معطل اتصال به Redis می‌شد
        return []

    def _get_connection(self):
        if self._connection is None:
            from redis import Redis

            self._connection = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        return self._connection

    def collect(self):
        redis_up = GaugeMetricFamily("ats_rq_redis_up", "آیا Redis صف کارها از دید بک‌اند در دسترس است (1/0)")
        try:
            from rq import Queue, Worker
            from rq.registry import DeferredJobRegistry, FailedJobRegistry, StartedJobRegistry
            from rq_scheduler import Scheduler

            connection = self._get_connection()
            queue = Queue(self._QUEUE_NAME, connection=connection)

            jobs = GaugeMetricFamily("ats_rq_jobs", "تعداد کارهای صف RQ به تفکیک وضعیت", labels=["queue", "state"])
            jobs.add_metric([self._QUEUE_NAME, "queued"], queue.count)
            jobs.add_metric([self._QUEUE_NAME, "started"], StartedJobRegistry(queue=queue).count)
            jobs.add_metric([self._QUEUE_NAME, "failed"], FailedJobRegistry(queue=queue).count)
            jobs.add_metric([self._QUEUE_NAME, "deferred"], DeferredJobRegistry(queue=queue).count)
            # یادآورهای مصاحبه که rq-scheduler برای آینده نگه داشته (app/core/interview_scheduler.py)
            jobs.add_metric(
                [self._QUEUE_NAME, "scheduled"], Scheduler(queue_name=self._QUEUE_NAME, connection=connection).count()
            )

            workers = GaugeMetricFamily("ats_rq_workers", "تعداد Workerهای فعال RQ")
            workers.add_metric([], Worker.count(connection=connection))

            redis_up.add_metric([], 1)
            yield jobs
            yield workers
        except Exception as error:  # noqa: BLE001 - Scrape هرگز نباید به‌خاطر Redis خطای 500 بدهد
            logger.warning("خواندن متریک‌های صف RQ ناموفق بود: %s", error)
            redis_up.add_metric([], 0)
        yield redis_up


_rq_collector_registered = False


def setup_metrics(app: FastAPI) -> None:
    """Middleware، Collector صف و مسیر /metrics را روی اپلیکیشن نصب می‌کند."""
    global _rq_collector_registered

    app.add_middleware(PrometheusMiddleware)

    if not _rq_collector_registered:
        REGISTRY.register(RQQueueCollector())
        _rq_collector_registered = True

    # عمداً sync (def، نه async def): FastAPI آن را در Thread Pool اجرا می‌کند،
    # پس فراخوانی‌های همگام Redis داخل RQQueueCollector هرگز Event Loop را قفل نمی‌کنند
    @app.get(METRICS_PATH, include_in_schema=False)
    def metrics() -> Response:
        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
