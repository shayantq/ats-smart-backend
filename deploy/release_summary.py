#!/usr/bin/env python3
"""
خلاصه‌ی نتیجه‌ی یک استقرار از روی گزارش پایشگر ترافیک (deploy/traffic_probe.py):

    release_summary.py markdown <probe.json> <tag> <url>
        → جدول Markdown برای Job Summary صفحه‌ی GitHub Actions
    release_summary.py event <probe.json> <tag> <url> <job-status> <actor> <run-url>
        → JSON آماده‌ی POST /api/v1/ops/events (اعلان داخل سایت تیم فنی)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load_probe(path: str) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def probe_line(probe: dict | None) -> str:
    if not probe:
        return "پایش ترافیک: گزارشی ثبت نشد"
    latency = probe["latency_ms"]
    return (
        f"ترافیک زنده حین استقرار: {probe['requests']} درخواست از {probe['virtual_users']} کاربر هم‌زمان، "
        f"{probe['failures']} خطا، p95={latency['p95']}ms"
    )


def markdown(probe: dict | None, tag: str, url: str) -> str:
    lines = ["## 🚀 استقرار Production", "", f"**نسخه:** `{tag}` · **دامنه:** {url}", ""]
    if probe:
        latency = probe["latency_ms"]
        verdict = "✅ بدون قطعی" if probe["failures"] == 0 else "❌ کاربران خطا دیدند"
        lines += [
            "| پایش ترافیک زنده حین استقرار | مقدار |",
            "|---|---|",
            f"| نتیجه | {verdict} |",
            f"| مدت پایش | {probe['duration_seconds']} ثانیه |",
            f"| کاربران مجازی هم‌زمان | {probe['virtual_users']} |",
            f"| کل درخواست‌ها | {probe['requests']} |",
            f"| درخواست‌های ناموفق | **{probe['failures']}** |",
            f"| زمان پاسخ p50 / p95 / p99 | {latency['p50']} / {latency['p95']} / {latency['p99']} ms |",
            "",
            "**جابه‌جایی نسخه‌ها (از دید کاربر):**",
            "",
        ]
        for item in probe["versions_seen"]:
            count = probe["responses_per_version"].get(item["version"], 0)
            lines.append(f"- `{item['version']}` از ساعت {item['first_seen']} — {count} پاسخ")
    else:
        lines.append(probe_line(None))
    return "\n".join(lines) + "\n"


def event(probe: dict | None, tag: str, url: str, status: str, actor: str, run_url: str) -> str:
    succeeded = status == "success" and bool(probe) and probe["failures"] == 0
    title = (
        f"🚀 نسخه‌ی {tag} بدون قطعی روی {url} مستقر شد"
        if succeeded
        else f"شکست استقرار نسخه‌ی {tag} روی Production — نسخه‌ی قبلی فعال ماند"
    )
    content = "\n".join([f"توسط: {actor}", probe_line(probe), f"Sanity Check و جزئیات: {run_url}"])
    payload = {"title": title, "content": content, "level": "success" if succeeded else "failure"}
    payload["category"] = "deployment"
    return json.dumps(payload, ensure_ascii=False)


def main() -> None:
    mode, probe_path, tag, url, *rest = sys.argv[1:]
    probe = load_probe(probe_path)
    if mode == "markdown":
        sys.stdout.write(markdown(probe, tag, url))
    elif mode == "event":
        status, actor, run_url = rest
        sys.stdout.write(event(probe, tag, url, status, actor, run_url))
    else:
        sys.exit(f"حالت نامعتبر: {mode}")


if __name__ == "__main__":
    # خروجی UTF-8 حتی روی کنسول ویندوز (Runner خودمیزبان)
    sys.stdout.reconfigure(encoding="utf-8")
    main()
