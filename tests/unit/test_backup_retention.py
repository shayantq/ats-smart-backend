"""تست واحد سیاست نگهداری بک‌آپ‌ها (backup/retention.py): ساعتی ۲ روز، روزانه ۳۰ روز، ماهانه ۱ سال."""

from datetime import datetime, timedelta, timezone

from backup.retention import BackupItem, parse_stamp, plan_deletions

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def _deleted_paths(items):
    return {item.path for item in plan_deletions(items, NOW)}


def test_hourly_wal_is_kept_for_two_days_only():
    wal = [BackupItem("wal", f"wal/{h}", NOW - timedelta(hours=h)) for h in range(0, 100)]

    deleted = _deleted_paths(wal)

    assert deleted == {f"wal/{h}" for h in range(49, 100)}  # بیش از ۴۸ ساعت
    assert "wal/48" not in deleted  # دقیقاً ۲ روز هنوز نگه داشته می‌شود


def test_wal_after_newest_full_backup_is_kept_even_if_older_than_two_days():
    """بک‌آپ شبانه ۵ روز شکست خورده: WAL های بعد از آخرین بک‌آپ کامل برای بازیابی لازم‌اند."""
    full = BackupItem("full", "full/last", NOW - timedelta(days=5))
    wal = [BackupItem("wal", f"wal/{h}", NOW - timedelta(hours=h)) for h in range(0, 24 * 7)]

    deleted = _deleted_paths([full, *wal])

    assert deleted == {f"wal/{h}" for h in range(24 * 5 + 1, 24 * 7)}  # فقط قبل از بک‌آپ کامل
    assert "full/last" not in deleted


def test_nightly_full_backups_for_one_year_keep_30_daily_plus_monthly():
    nightly = [
        BackupItem("full", f"full/{day}", datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc) - timedelta(days=day))
        for day in range(0, 400)
    ]

    kept = [item for item in nightly if item.path not in _deleted_paths(nightly)]

    daily_kept = [item for item in kept if NOW - item.created_at <= timedelta(days=30)]
    monthly_kept = [item for item in kept if NOW - item.created_at > timedelta(days=30)]
    assert len(daily_kept) == 30
    # هر ماهِ قدیمی‌تر از ۳۰ روز فقط یک بک‌آپ (اولین روز ماه) — و هیچ‌کدام قدیمی‌تر از ۱ سال
    assert all(item.created_at.day == 1 for item in monthly_kept)
    assert all(NOW - item.created_at <= timedelta(days=365) for item in monthly_kept)
    assert len({(item.created_at.year, item.created_at.month) for item in monthly_kept}) == len(monthly_kept)
    assert 10 <= len(monthly_kept) <= 12


def test_newest_full_backup_is_never_deleted_even_if_very_old():
    """اگر سرویس بک‌آپ مدتی متوقف بوده باشد، آخرین بک‌آپ موجود نباید حذف شود."""
    ancient = BackupItem("full", "full/only-one", NOW - timedelta(days=900))

    assert plan_deletions([ancient], NOW) == []


def test_weekly_resume_backups_follow_daily_and_monthly_rules():
    weekly = [BackupItem("resumes", f"resumes/{week}", NOW - timedelta(weeks=week)) for week in range(0, 60)]

    deleted = _deleted_paths(weekly)

    assert all(f"resumes/{week}" not in deleted for week in range(0, 5))  # ۴ هفته‌ی اخیر (≤ ۳۰ روز)
    assert "resumes/59" in deleted  # بیش از یک سال


def test_parse_stamp_is_utc():
    assert parse_stamp("20261013T020000Z") == datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc)
