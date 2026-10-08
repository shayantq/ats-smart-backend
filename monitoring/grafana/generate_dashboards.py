"""
تولیدکننده‌ی داشبوردهای Grafana (خروجی: monitoring/grafana/dashboards/*.json).

چرا تولیدکننده به‌جای JSON دست‌نویس؟ JSON داشبورد Grafana حجیم و تکراری است؛
تعریف پنل‌ها در پایتون خواناتر است و همه‌ی پنل‌ها قواعد یکسانی دارند:
- اعداد کلیدی (عنوان یک نگاه) = Stat Tile با آستانه‌های وضعیت سبز/نارنجی/قرمز
- روند زمانی = Time series با خط ۲px، فقط یک محور (هر واحد = یک پنل جدا)
- بیش از یک سری = Legend همیشه نمایش داده می‌شود؛ Tooltip چندسری

اجرا بعد از هر تغییر:   python monitoring/grafana/generate_dashboards.py
"""

import json
from pathlib import Path

DATASOURCE = {"type": "prometheus", "uid": "prometheus"}
OUTPUT_DIR = Path(__file__).resolve().parent / "dashboards"


def _thresholds(*steps: tuple[float | None, str]) -> dict:
    return {"mode": "absolute", "steps": [{"value": value, "color": color} for value, color in steps]}


def stat(title, expr, *, unit, x, y, w=4, h=4, thresholds=None, decimals=None, description=""):
    defaults = {
        "unit": unit,
        "color": {"mode": "thresholds"},
        "thresholds": thresholds or _thresholds((None, "text")),
    }
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": DATASOURCE,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": "A", "expr": expr, "instant": False}],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "center",
            "textMode": "value",
        },
    }


def timeseries(title, targets, *, unit, x, y, w=12, h=8, min_value=0, max_value=None, thresholds=None, description=""):
    defaults = {
        "unit": unit,
        "min": min_value,
        "color": {"mode": "palette-classic"},
        "custom": {
            "lineWidth": 2,
            "fillOpacity": 8,
            "gradientMode": "none",
            "showPoints": "never",
            "spanNulls": True,
            "axisSoftMin": 0,
            # خط آستانه‌ی هشدار (اگر تعریف شده) روی خود نمودار دیده شود
            "thresholdsStyle": {"mode": "line+area" if thresholds else "off"},
        },
    }
    if max_value is not None:
        defaults["max"] = max_value
    if thresholds:
        defaults["thresholds"] = thresholds
    return {
        "type": "timeseries",
        "title": title,
        "description": description,
        "datasource": DATASOURCE,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [
            {"refId": chr(ord("A") + index), "expr": expr, "legendFormat": legend}
            for index, (expr, legend) in enumerate(targets)
        ],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def row(title, y):
    return {
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
        "panels": [],
    }


def dashboard(uid, title, description, panels):
    for panel_id, panel in enumerate(panels, start=1):
        panel["id"] = panel_id
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": ["ats-smart"],
        "timezone": "browser",
        "editable": True,
        "graphTooltip": 1,  # Crosshair مشترک بین همه‌ی پنل‌ها
        "refresh": "10s",  # نمایش زنده
        "time": {"from": "now-1h", "to": "now"},
        "schemaVersion": 39,
        "version": 1,
        "panels": panels,
        "templating": {"list": []},
        "annotations": {"list": []},
    }


# آستانه‌های وضعیت — هم‌خوان با قوانین هشدار (monitoring/prometheus/alerts.yml)
USAGE_THRESHOLDS = _thresholds((None, "green"), (70, "orange"), (85, "red"))
ERROR_RATE_THRESHOLDS = _thresholds((None, "green"), (1, "orange"), (5, "red"))
LATENCY_THRESHOLDS = _thresholds((None, "green"), (0.5, "orange"), (1, "red"))

CPU_PERCENT = '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[2m]))) * 100'
RAM_PERCENT = "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100"
DISK_FREE_PERCENT = (
    'min(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"}'
    ' / node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"}) * 100'
)

RPS = 'sum(rate(http_requests_total{job="backend_api"}[1m]))'
ERROR_RATE = (
    'sum(rate(http_requests_total{job="backend_api",status=~"5.."}[2m]))'
    ' / sum(rate(http_requests_total{job="backend_api"}[2m])) * 100'
)


def latency_quantile(q: float, by: str = "") -> str:
    group = f"le{', ' + by if by else ''}"
    return (
        f"histogram_quantile({q}, sum by ({group}) "
        f'(rate(http_request_duration_seconds_bucket{{job="backend_api"}}[5m])))'
    )


system_overview = dashboard(
    "ats-system-overview",
    "ATS Smart — سلامت سیستم",
    "منابع سرور، پایگاه داده، Redis و صف کارهای پس‌زمینه — به‌صورت زنده",
    [
        row("نمای کلی", 0),
        stat("CPU", CPU_PERCENT, unit="percent", x=0, y=1, thresholds=USAGE_THRESHOLDS, decimals=1),
        stat(
            "RAM",
            RAM_PERCENT,
            unit="percent",
            x=4,
            y=1,
            thresholds=USAGE_THRESHOLDS,
            decimals=1,
            description="هشدار بحرانی بالای ۸۵٪",
        ),
        stat(
            "فضای خالی دیسک",
            DISK_FREE_PERCENT,
            unit="percent",
            x=8,
            y=1,
            thresholds=_thresholds((None, "red"), (10, "orange"), (20, "green")),
            decimals=1,
        ),
        stat("کانکشن‌های فعال دیتابیس", "sum(pg_stat_activity_count)", unit="short", x=12, y=1),
        stat(
            "کارهای منتظر در صف",
            'max(ats_rq_jobs{state="queued"})',
            unit="short",
            x=16,
            y=1,
            thresholds=_thresholds((None, "green"), (20, "orange"), (50, "red")),
        ),
        stat(
            "Workerهای فعال صف",
            "max(ats_rq_workers)",
            unit="short",
            x=20,
            y=1,
            thresholds=_thresholds((None, "red"), (1, "green")),
        ),
        row("منابع سرور", 5),
        timeseries(
            "مصرف CPU و RAM",
            [(CPU_PERCENT, "CPU"), (RAM_PERCENT, "RAM")],
            unit="percent",
            x=0,
            y=6,
            max_value=100,
            thresholds=_thresholds((None, "transparent"), (85, "red")),
            description="ناحیه‌ی قرمز = آستانه‌ی هشدار ۸۵٪",
        ),
        timeseries(
            "ترافیک شبکه",
            [
                ('sum(rate(node_network_receive_bytes_total{device!~"lo|veth.*|br.*|docker.*"}[2m]))', "دریافت"),
                ('sum(rate(node_network_transmit_bytes_total{device!~"lo|veth.*|br.*|docker.*"}[2m]))', "ارسال"),
            ],
            unit="Bps",
            x=12,
            y=6,
        ),
        timeseries(
            "حافظه‌ی پردازه‌های بک‌اند (RSS)",
            [('process_resident_memory_bytes{job="backend_api"}', "{{instance}}")],
            unit="bytes",
            x=0,
            y=14,
        ),
        timeseries(
            "CPU پردازه‌های بک‌اند",
            [('rate(process_cpu_seconds_total{job="backend_api"}[2m]) * 100', "{{instance}}")],
            unit="percent",
            x=12,
            y=14,
        ),
        row("پایگاه داده و Redis", 22),
        timeseries(
            "کانکشن‌های PostgreSQL به تفکیک وضعیت",
            [('sum by (state) (pg_stat_activity_count{state!=""})', "{{state}}")],
            unit="short",
            x=0,
            y=23,
        ),
        timeseries(
            "تراکنش‌های PostgreSQL",
            [
                ("sum(rate(pg_stat_database_xact_commit[2m]))", "Commit"),
                ("sum(rate(pg_stat_database_xact_rollback[2m]))", "Rollback"),
            ],
            unit="ops",
            x=12,
            y=23,
        ),
        timeseries(
            "حافظه‌ی مصرفی Redis",
            [("redis_memory_used_bytes", "مصرف‌شده")],
            unit="bytes",
            x=0,
            y=31,
        ),
        timeseries(
            "کلاینت‌های متصل به Redis",
            [("redis_connected_clients", "کلاینت‌ها")],
            unit="short",
            x=12,
            y=31,
        ),
        row("صف کارهای پس‌زمینه (RQ)", 39),
        timeseries(
            "کارهای صف به تفکیک وضعیت",
            [("max by (state) (ats_rq_jobs)", "{{state}}")],
            unit="short",
            x=0,
            y=40,
            description="queued: منتظر · started: در حال اجرا · failed: شکست‌خورده · scheduled: یادآورهای آینده",
        ),
        timeseries(
            "Workerهای فعال",
            [("max(ats_rq_workers)", "Workers")],
            unit="short",
            x=12,
            y=40,
        ),
    ],
)

api_performance = dashboard(
    "ats-api-performance",
    "ATS Smart — کارایی API",
    "نرخ درخواست در ثانیه (RPS)، زمان پاسخ (Latency) و نرخ خطای بک‌اند FastAPI",
    [
        row("نمای کلی", 0),
        stat("درخواست در ثانیه (RPS)", RPS, unit="reqps", x=0, y=1, w=6, decimals=2),
        stat(
            "نرخ خطای سرور (5xx)",
            ERROR_RATE,
            unit="percent",
            x=6,
            y=1,
            w=6,
            thresholds=ERROR_RATE_THRESHOLDS,
            decimals=2,
            description="هشدار بحرانی بالای ۵٪",
        ),
        stat(
            "زمان پاسخ p95",
            latency_quantile(0.95),
            unit="s",
            x=12,
            y=1,
            w=6,
            thresholds=LATENCY_THRESHOLDS,
            decimals=3,
        ),
        stat(
            "درخواست‌های در حال پردازش",
            'sum(http_requests_in_progress{job="backend_api"})',
            unit="short",
            x=18,
            y=1,
            w=6,
        ),
        row("ترافیک", 5),
        timeseries(
            "RPS به تفکیک کلاس پاسخ",
            [
                (
                    'sum by (status_class) (label_replace(rate(http_requests_total{job="backend_api"}[1m]),'
                    ' "status_class", "${1}xx", "status", "(\\\\d).."))',
                    "{{status_class}}",
                )
            ],
            unit="reqps",
            x=0,
            y=6,
        ),
        timeseries(
            "نرخ خطای سرور (5xx)",
            [(ERROR_RATE, "نرخ خطا")],
            unit="percent",
            x=12,
            y=6,
            thresholds=_thresholds((None, "transparent"), (5, "red")),
            description="ناحیه‌ی قرمز = آستانه‌ی هشدار ۵٪",
        ),
        timeseries(
            "RPS پرترافیک‌ترین مسیرها (۱۰ مسیر)",
            [('topk(10, sum by (route) (rate(http_requests_total{job="backend_api"}[5m])))', "{{route}}")],
            unit="reqps",
            x=0,
            y=14,
            w=24,
            h=9,
        ),
        row("زمان پاسخ (Latency)", 23),
        timeseries(
            "زمان پاسخ کل API — p50 / p95 / p99",
            [
                (latency_quantile(0.50), "p50"),
                (latency_quantile(0.95), "p95"),
                (latency_quantile(0.99), "p99"),
            ],
            unit="s",
            x=0,
            y=24,
            thresholds=_thresholds((None, "transparent"), (1, "red")),
            description="ناحیه‌ی قرمز = آستانه‌ی هشدار p95 بالای ۱ ثانیه",
        ),
        timeseries(
            "کندترین مسیرها — p95 (۱۰ مسیر)",
            [("topk(10, " + latency_quantile(0.95, "route") + ")", "{{route}}")],
            unit="s",
            x=12,
            y=24,
        ),
    ],
)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for board in (system_overview, api_performance):
        path = OUTPUT_DIR / f"{board['uid']}.json"
        path.write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"written: {path.name} ({len(board['panels'])} panels)")


if __name__ == "__main__":
    main()
