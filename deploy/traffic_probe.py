#!/usr/bin/env python3
"""
پایشگر ترافیک زنده حین استقرار — اثبات «بدون قطعی و بدون افت کیفیت برای کاربر نهایی».

چند کاربر مجازی هم‌زمان، از بیرون و دقیقاً از مسیر کاربر واقعی (دامنه → gateway → frontend →
backend → دیتابیس) به‌طور پیوسته صفحه‌ی اصلی، API سلامت و یک API وابسته به دیتابیس را درخواست
می‌کنند. هر پاسخ غیر 2xx یا خطای اتصال/Timeout یک «خطای کاربر» حساب می‌شود. نسخه‌ی سروردهنده‌ی
هر پاسخ (فیلد version در /api/v1/health) ثبت می‌شود تا لحظه‌ی جابه‌جایی نسخه دیده شود.

    python deploy/traffic_probe.py --url http://smart-ats.localhost --stop-file /tmp/probe.stop

فقط کتابخانه‌ی استاندارد پایتون (روی هر سرور/Runner بدون نصب چیزی اجرا می‌شود).
خروجی: خلاصه‌ی متنی + فایل JSON (--report)؛ کد خروج ۱ اگر حتی یک درخواست ناموفق بوده باشد.
"""

from __future__ import annotations

import argparse
import http.client
import json
import socket
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

# مسیرهایی که در همه‌ی نسخه‌ها وجود دارند (نسخه‌ی قدیم و جدید هر دو باید پاسخ بدهند)
PATHS = ["/", "/api/v1/health", "/api/v1/jobs/?limit=5"]
LATENCY_SLO_SECONDS = 2.0


class Probe:
    def __init__(self, url: str, users: int, interval: float):
        parts = urlsplit(url)
        self.host_header = parts.netloc
        self.port = parts.port or 80
        # دامنه‌های *.localhost را مرورگرها و curl خودشان به 127.0.0.1 می‌برند؛ پایتون روی ویندوز نه
        hostname = parts.hostname or "localhost"
        self.connect_host = "127.0.0.1" if hostname.endswith(".localhost") else hostname
        self.users = users
        self.interval = interval
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.total = 0
        self.failures: list[dict] = []
        self.latencies: list[float] = []
        self.statuses: Counter = Counter()
        self.versions: list[tuple[float, str]] = []  # (زمان اولین مشاهده، نسخه)
        self.version_counts: Counter = Counter()
        self.started = time.time()

    def _connect(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(self.connect_host, self.port, timeout=10)

    def _request(self, connection: http.client.HTTPConnection, path: str) -> tuple[int, bytes]:
        connection.request("GET", path, headers={"Host": self.host_header, "User-Agent": "ats-traffic-probe"})
        response = connection.getresponse()
        return response.status, response.read()

    def _user(self, index: int) -> None:
        # مثل مرورگر: یک اتصال Keep-Alive برای هر کاربر. اگر سرور یک اتصال «بیکار» را بسته باشد
        # (مثلاً reload شدن nginx)، مرورگرها درخواست GET را بی‌صدا روی اتصال تازه تکرار می‌کنند
        # (RFC 9110 §9.2.2) — همین رفتار اینجا هم هست؛ هر خطای دیگری «خطای کاربر» است.
        # (اتصال تازه برای هر درخواست، پورت‌های موقت ویندوزِ خودِ پایشگر را تمام می‌کرد.)
        connection = self._connect()
        cycle = index
        while not self.stop.is_set():
            path = PATHS[cycle % len(PATHS)]
            cycle += 1
            began = time.perf_counter()
            try:
                try:
                    status, body = self._request(connection, path)
                except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
                    connection.close()
                    connection = self._connect()
                    status, body = self._request(connection, path)
                error = None if 200 <= status < 300 else f"HTTP {status}"
            except (OSError, http.client.HTTPException, socket.timeout) as exc:
                status, body, error = 0, b"", f"{type(exc).__name__}: {exc}"[:120]
                connection.close()
                connection = self._connect()
            elapsed = time.perf_counter() - began
            with self.lock:
                self.total += 1
                self.latencies.append(elapsed)
                self.statuses[status] += 1
                if error:
                    self.failures.append({"time": datetime.now().strftime("%H:%M:%S"), "path": path, "error": error})
                elif path == "/api/v1/health":
                    version = json.loads(body).get("version", "?")
                    self.version_counts[version] += 1
                    if not self.versions or self.versions[-1][1] != version:
                        if version not in {v for _, v in self.versions}:
                            self.versions.append((time.time(), version))
            self.stop.wait(self.interval)
        connection.close()

    def run(self, duration: float, stop_file: Path | None) -> None:
        threads = [threading.Thread(target=self._user, args=(i,), daemon=True) for i in range(self.users)]
        for thread in threads:
            thread.start()
        deadline = self.started + duration
        last_report = time.time()
        while time.time() < deadline and not (stop_file and stop_file.exists()):
            time.sleep(0.5)
            if time.time() - last_report >= 15:
                last_report = time.time()
                with self.lock:
                    print(
                        f"[probe {datetime.now():%H:%M:%S}] درخواست‌ها={self.total} خطا={len(self.failures)} "
                        f"نسخه‌ها={dict(self.version_counts)}",
                        flush=True,
                    )
        self.stop.set()
        for thread in threads:
            thread.join(timeout=15)

    def summary(self) -> dict:
        ordered = sorted(self.latencies) or [0.0]

        def percentile(q: float) -> float:
            return ordered[min(len(ordered) - 1, int(q * len(ordered)))]

        return {
            "duration_seconds": round(time.time() - self.started),
            "virtual_users": self.users,
            "requests": self.total,
            "failures": len(self.failures),
            "failure_samples": self.failures[:20],
            "status_codes": {str(code): count for code, count in sorted(self.statuses.items())},
            "latency_ms": {
                "p50": round(percentile(0.50) * 1000),
                "p95": round(percentile(0.95) * 1000),
                "p99": round(percentile(0.99) * 1000),
                "max": round(ordered[-1] * 1000),
            },
            "versions_seen": [
                {"version": version, "first_seen": datetime.fromtimestamp(ts).strftime("%H:%M:%S")}
                for ts, version in self.versions
            ],
            "responses_per_version": dict(self.version_counts),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="آدرس عمومی سایت، مثلاً http://smart-ats.localhost")
    parser.add_argument("--users", type=int, default=20, help="تعداد کاربران مجازی هم‌زمان")
    parser.add_argument("--interval", type=float, default=0.2, help="مکث هر کاربر بین درخواست‌ها (ثانیه)")
    parser.add_argument("--duration", type=float, default=1800, help="حداکثر مدت (ثانیه)")
    parser.add_argument("--stop-file", type=Path, help="با ساخته‌شدن این فایل، پایش متوقف می‌شود")
    parser.add_argument("--report", type=Path, help="ذخیره‌ی نتیجه به‌صورت JSON")
    args = parser.parse_args()

    probe = Probe(args.url, args.users, args.interval)
    print(f"[probe] شروع: {args.users} کاربر مجازی → {args.url} ({', '.join(PATHS)})", flush=True)
    probe.run(args.duration, args.stop_file)
    result = probe.summary()
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    latency = result["latency_ms"]
    print("\n=================== نتیجه‌ی پایش ترافیک حین استقرار ===================")
    print(f"مدت: {result['duration_seconds']} ثانیه · کاربران هم‌زمان: {result['virtual_users']}")
    print(f"کل درخواست‌ها: {result['requests']} · ناموفق: {result['failures']} · کدها: {result['status_codes']}")
    print(f"زمان پاسخ: p50={latency['p50']}ms  p95={latency['p95']}ms  p99={latency['p99']}ms  max={latency['max']}ms")
    for item in result["versions_seen"]:
        count = result["responses_per_version"][item["version"]]
        print(f"نسخه‌ی {item['version']}: از {item['first_seen']} ({count} پاسخ)")
    for sample in result["failure_samples"]:
        print(f"  ✘ {sample['time']} {sample['path']} → {sample['error']}")

    ok = result["failures"] == 0 and result["requests"] > 0 and latency["p95"] <= LATENCY_SLO_SECONDS * 1000
    verdict = "PASS" if ok else "FAIL"
    print(
        f"[ZERO-DOWNTIME {verdict}] {result['requests']} درخواست، {result['failures']} خطا، "
        f"p95={latency['p95']}ms (حد مجاز {LATENCY_SLO_SECONDS * 1000:.0f}ms)"
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    # خروجی UTF-8 حتی روی کنسول ویندوز (Runner خودمیزبان)
    sys.stdout.reconfigure(encoding="utf-8")
    main()
