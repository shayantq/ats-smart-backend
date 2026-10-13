"""
سیاست نگهداری (Retention Policy) بک‌آپ‌ها — منطق خالص و بدون وابستگی به زمان واقعی یا شبکه،
تا با تست واحد قابل‌اثبات باشد (tests/unit/test_backup_retention.py).

سه لایه (GFS ساده‌شده):
    ساعتی  (WAL افزایشی)            → تا ۲ روز
    روزانه (بک‌آپ کامل شبانه)        → تا ۳۰ روز
    ماهانه (اولین بک‌آپ کامل هر ماه)  → تا ۱ سال

بک‌آپ‌های هفتگی رزومه‌ها هم همان قاعده‌ی روزانه/ماهانه را دارند. جدیدترین بک‌آپ کامل هرگز حذف
نمی‌شود — حتی اگر به هر دلیلی (مثلاً توقف طولانی سرویس) از همه‌ی بازه‌ها قدیمی‌تر شده باشد.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

HOURLY_RETENTION = timedelta(days=2)
DAILY_RETENTION = timedelta(days=30)
MONTHLY_RETENTION = timedelta(days=365)

STAMP_FORMAT = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True)
class BackupItem:
    """یک واحد قابل‌حذف در فضای Offsite: یک سگمنت WAL، یا یک مجموعه‌ی بک‌آپ کامل/رزومه."""

    kind: str  # "wal" | "full" | "resumes"
    path: str
    created_at: datetime


def plan_deletions(
    items: list[BackupItem],
    now: datetime,
    hourly: timedelta = HOURLY_RETENTION,
    daily: timedelta = DAILY_RETENTION,
    monthly: timedelta = MONTHLY_RETENTION,
) -> list[BackupItem]:
    """فهرست آیتم‌هایی که طبق سیاست نگهداری باید حذف شوند (بدون انجام حذف)."""
    # WAL های بعد از جدیدترین بک‌آپ کامل هرگز حذف نمی‌شوند: بدون آن‌ها بازیابی تا آخرین ساعت
    # ممکن نیست (مثلاً اگر بک‌آپ شبانه چند روز شکست خورده باشد)
    fulls = [item.created_at for item in items if item.kind == "full"]
    wal_floor = max(fulls) if fulls else None
    expired = [
        item
        for item in items
        if item.kind == "wal" and now - item.created_at > hourly and (wal_floor is None or item.created_at < wal_floor)
    ]
    for kind in ("full", "resumes"):
        expired.extend(_expired_snapshots([item for item in items if item.kind == kind], now, daily, monthly))
    return sorted(expired, key=lambda item: (item.kind, item.created_at))


def _expired_snapshots(
    snapshots: list[BackupItem], now: datetime, daily: timedelta, monthly: timedelta
) -> list[BackupItem]:
    if not snapshots:
        return []
    ordered = sorted(snapshots, key=lambda item: item.created_at)
    newest = ordered[-1]

    # اولین بک‌آپ هر ماه تقویمی، نماینده‌ی «ماهانه»ی آن ماه است
    first_of_month: dict[tuple[int, int], BackupItem] = {}
    for item in ordered:
        first_of_month.setdefault((item.created_at.year, item.created_at.month), item)
    monthly_representatives = set(first_of_month.values())

    expired = []
    for item in ordered:
        age = now - item.created_at
        keep = item is newest or age <= daily or (item in monthly_representatives and age <= monthly)
        if not keep:
            expired.append(item)
    return expired


def parse_stamp(stamp: str) -> datetime:
    """«20261013T020000Z» → datetime (UTC). نام هر بک‌آپ کامل/رزومه با همین مُهر زمانی ساخته می‌شود."""
    return datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=timezone.utc)
