#!/usr/bin/env python3
"""
ats-backup — پشتیبان‌گیری و بازیابی فاجعه‌ی ATS Smart (داخل کانتینر سرویس backup اجرا می‌شود).

دستورها (زمان‌بندی خودکار در backup/crontab):
    full            بک‌آپ کامل شبانه (۰۲:۰۰): pg_basebackup (فیزیکی، پایه‌ی PITR) + pg_dump (منطقی)
    wal             بک‌آپ افزایشی ساعتی: سوییچ WAL و ارسال همه‌ی سگمنت‌های جدید
    resumes         بک‌آپ هفتگی فایل‌های رزومه
    retention       اعمال سیاست نگهداری (پس از هر بک‌آپ هم خودکار اجرا می‌شود)
    list            فهرست بک‌آپ‌های موجود در Offsite
    restore-pitr    بازیابی دیتابیس از Offsite در یک پوشه‌ی خالی (تا آخرین لحظه یا یک زمان مشخص)
    restore-resumes بازیابی فایل‌های رزومه از آخرین بک‌آپ هفتگی
    drill           تمرین بازیابی فاجعه: restore-pitr + بالا آوردن PostgreSQL + اجرای یک کوئری بررسی
    fetch-wal       (برای restore_command پستگرس) دریافت و رمزگشایی یک سگمنت WAL

امنیت: هر فایل بلافاصله در لحظه‌ی تولید و پیش از نوشتن روی دیسک، فشرده و با age رمزنگاری می‌شود
(producer | zstd | age). سرویس backup فقط «کلید عمومی» را دارد؛ «کلید خصوصی» فقط هنگام بازیابی
و جدا از سرور استفاده می‌شود — حتی نفوذ به سرور اصلی هم بک‌آپ‌ها را قابل‌خواندن نمی‌کند.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retention import STAMP_FORMAT, BackupItem, parse_stamp, plan_deletions  # noqa: E402

REMOTE = os.environ.get("BACKUP_REMOTE", "offsite:ats-backups").rstrip("/")
WAL_ARCHIVE_DIR = Path(os.environ.get("WAL_ARCHIVE_DIR", "/wal_archive"))
MEDIA_DIR = Path(os.environ.get("MEDIA_DIR", "/media"))
METRICS_DIR = Path(os.environ.get("METRICS_DIR", "/metrics"))
RECIPIENT_FILE = os.environ.get("BACKUP_AGE_RECIPIENT_FILE", "/run/secrets/backup-public/age-recipient.txt")
IDENTITY_FILE = os.environ.get("BACKUP_AGE_IDENTITY_FILE", "/run/secrets/backup-private/age-identity.txt")
LOCK_FILE = "/tmp/ats-backup.lock"


# ---------------------------------------------------------------------------
# ابزارهای پایه
# ---------------------------------------------------------------------------
def log(message: str) -> None:
    print(f"[ats-backup {datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def recipient() -> str:
    key = os.environ.get("BACKUP_AGE_RECIPIENT") or _read_first_line(RECIPIENT_FILE)
    if not key or not key.startswith("age1"):
        sys.exit("کلید عمومی رمزنگاری (age1...) تنظیم نشده — بنگرید README بخش «پشتیبان‌گیری»")
    return key


def _read_first_line(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return None


def pipeline(*commands: list[str], stdin=None, stdout=None) -> None:
    """اجرای زنجیره‌ی cmd1 | cmd2 | ... و Fail در صورت خطای هر مرحله (نه فقط آخری)."""
    processes = []
    previous = stdin
    for index, command in enumerate(commands):
        is_last = index == len(commands) - 1
        process = subprocess.Popen(command, stdin=previous, stdout=stdout if is_last else subprocess.PIPE)
        if previous is not None and previous is not stdin:
            previous.close()  # فقط فرآیند بعدی خروجی را می‌خواند (برای رسیدن SIGPIPE در صورت خطا)
        previous = process.stdout
        processes.append(process)
    for command, process in zip(commands, processes):
        if process.wait() != 0:
            raise RuntimeError(f"مرحله‌ی «{command[0]}» با کد {process.returncode} شکست خورد")


def encrypt_to_file(producer: list[str], destination: Path) -> None:
    """producer | zstd | age → destination  (نسخه‌ی رمزنگاری‌نشده هرگز روی دیسک نوشته نمی‌شود)."""
    pipeline(producer, ["zstd", "-q", "-c", "-T0"], ["age", "-r", recipient(), "-o", str(destination)])


def rclone(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["rclone", "--retries", "5", "--low-level-retries", "10", *args],
        check=True,
        capture_output=capture,
        text=True,
    )
    return result.stdout if capture else ""


def configure_offsite_credentials() -> None:
    """rclone رمز SFTP را فقط به شکل obscure می‌پذیرد؛ رمز ساده از OFFSITE_SFTP_PASSWORD تبدیل می‌شود
    (برای همه‌ی پردازه‌های فرزند هم، از جمله restore_command پستگرس هنگام بازیابی)."""
    password = os.environ.get("OFFSITE_SFTP_PASSWORD")
    if password and not os.environ.get("RCLONE_CONFIG_OFFSITE_PASS"):
        obscured = subprocess.run(["rclone", "obscure", password], check=True, capture_output=True, text=True)
        os.environ["RCLONE_CONFIG_OFFSITE_PASS"] = obscured.stdout.strip()


def upload(local: Path, remote_path: str) -> None:
    # rclone اندازه/هش را پس از انتقال تأیید می‌کند؛ در صورت عدم تطابق، خطا می‌دهد
    rclone("copyto", str(local), f"{REMOTE}/{remote_path}")


def psql(sql: str) -> str:
    return subprocess.run(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atc", sql], check=True, capture_output=True, text=True
    ).stdout.strip()


def write_metric(kind: str, size_bytes: int) -> None:
    """زمان/حجم آخرین بک‌آپ موفق برای Prometheus (node_exporter textfile) — هشدار «بک‌آپ متوقف شده»."""
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    state_file = METRICS_DIR / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    state[kind] = {"timestamp": int(time.time()), "size": size_bytes}
    state_file.write_text(json.dumps(state))

    lines = [
        "# HELP ats_backup_last_success_timestamp_seconds زمان آخرین بک‌آپ موفق (Unix)",
        "# TYPE ats_backup_last_success_timestamp_seconds gauge",
        *(f'ats_backup_last_success_timestamp_seconds{{kind="{k}"}} {v["timestamp"]}' for k, v in state.items()),
        "# HELP ats_backup_last_size_bytes حجم رمزنگاری‌شده‌ی آخرین بک‌آپ موفق",
        "# TYPE ats_backup_last_size_bytes gauge",
        *(f'ats_backup_last_size_bytes{{kind="{k}"}} {v["size"]}' for k, v in state.items()),
    ]
    temporary = METRICS_DIR / "ats_backup.prom.tmp"
    temporary.write_text("\n".join(lines) + "\n")
    temporary.replace(METRICS_DIR / "ats_backup.prom")


class SingleRun:
    """قفل سراسری: بک‌آپ کامل ۰۲:۰۰ و بک‌آپ ساعتی هم‌زمان اجرا نشوند."""

    def __enter__(self):
        self._handle = open(LOCK_FILE, "w")
        fcntl.flock(self._handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._handle, fcntl.LOCK_UN)
        self._handle.close()


# ---------------------------------------------------------------------------
# پشتیبان‌گیری
# ---------------------------------------------------------------------------
def cmd_full(_args) -> None:
    stamp = utc_now().strftime(STAMP_FORMAT)
    with SingleRun(), tempfile.TemporaryDirectory(prefix="ats-full-") as tmp:
        work = Path(tmp)
        log(f"بک‌آپ کامل {stamp}: pg_basebackup (فیزیکی، پایه‌ی بازیابی لحظه‌ای)")
        encrypt_to_file(
            ["pg_basebackup", "-D", "-", "-Ft", "-X", "fetch", "--checkpoint=fast", "--no-password"],
            work / "base.tar.zst.age",
        )
        log("pg_dump (منطقی، قابل بازیابی روی هر نسخه/سرور)")
        encrypt_to_file(["pg_dump", "-Fc", "-Z0", "--no-password"], work / "database.dump.zst.age")

        manifest = {
            "created_at": stamp,
            "database": os.environ.get("PGDATABASE"),
            "server_version": psql("show server_version"),
            "files": {path.name: path.stat().st_size for path in work.iterdir()},
        }
        (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

        total = 0
        for path in sorted(work.iterdir()):
            upload(path, f"full/{stamp}/{path.name}")
            total += path.stat().st_size
        log(f"✔ بک‌آپ کامل منتقل شد: full/{stamp} ({total / 1_048_576:.1f} MB رمزنگاری‌شده)")
        write_metric("full", total)
    cmd_retention(argparse.Namespace(dry_run=False))


def cmd_wal(_args) -> None:
    with SingleRun():
        # سوییچ WAL: همه‌ی تغییرات تا همین لحظه در یک سگمنت بسته و آرشیو می‌شوند — بیشترین هدررفت
        # ممکن در صورت فاجعه = فاصله‌ی دو اجرای همین دستور (هر ساعت)
        segment = psql("select pg_walfile_name(pg_switch_wal())")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            archived = psql("select coalesce(last_archived_wal, '') from pg_stat_archiver")
            if archived >= segment or (WAL_ARCHIVE_DIR / segment).exists():
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"سگمنت {segment} در ۲ دقیقه آرشیو نشد — archive_command را بررسی کنید")

        pending = sorted(
            path for path in WAL_ARCHIVE_DIR.iterdir() if path.is_file() and not path.name.endswith(".tmp")
        )
        total = 0
        with tempfile.TemporaryDirectory(prefix="ats-wal-") as tmp:
            for path in pending:
                encrypted = Path(tmp) / f"{path.name}.zst.age"
                encrypt_to_file(["cat", str(path)], encrypted)
                upload(encrypted, f"wal/{encrypted.name}")
                total += encrypted.stat().st_size
                encrypted.unlink()
                path.unlink()  # فقط پس از انتقال موفق به Offsite
        log(f"✔ بک‌آپ افزایشی: {len(pending)} فایل WAL منتقل شد (تا سگمنت {segment})")
        write_metric("wal", total)
    cmd_retention(argparse.Namespace(dry_run=False))


def cmd_resumes(_args) -> None:
    source = MEDIA_DIR / "resumes"
    if not source.exists():
        log(f"پوشه‌ی {source} وجود ندارد — رزومه‌ای برای بک‌آپ نیست")
        return
    stamp = utc_now().strftime(STAMP_FORMAT)
    with SingleRun(), tempfile.TemporaryDirectory(prefix="ats-resumes-") as tmp:
        encrypted = Path(tmp) / f"{stamp}.tar.zst.age"
        encrypt_to_file(["tar", "-C", str(MEDIA_DIR), "-cf", "-", "resumes"], encrypted)
        upload(encrypted, f"resumes/{encrypted.name}")
        size = encrypted.stat().st_size
        log(f"✔ بک‌آپ هفتگی رزومه‌ها منتقل شد: resumes/{encrypted.name} ({size / 1_048_576:.1f} MB)")
        write_metric("resumes", size)
    cmd_retention(argparse.Namespace(dry_run=False))


# ---------------------------------------------------------------------------
# فهرست و نگهداری
# ---------------------------------------------------------------------------
def inventory() -> list[BackupItem]:
    try:
        listing = json.loads(rclone("lsjson", "-R", "--files-only", REMOTE, capture=True) or "[]")
    except subprocess.CalledProcessError:
        return []
    items: dict[str, BackupItem] = {}
    for entry in listing:
        parts = entry["Path"].split("/")
        if parts[0] == "full" and len(parts) == 3:
            items[f"full/{parts[1]}"] = BackupItem("full", f"full/{parts[1]}", parse_stamp(parts[1]))
        elif parts[0] == "resumes" and len(parts) == 2:
            items[entry["Path"]] = BackupItem("resumes", entry["Path"], parse_stamp(parts[1].split(".")[0]))
        elif parts[0] == "wal" and len(parts) == 2:
            modified = datetime.fromisoformat(entry["ModTime"].replace("Z", "+00:00"))
            items[entry["Path"]] = BackupItem("wal", entry["Path"], modified)
    return sorted(items.values(), key=lambda item: (item.kind, item.created_at))


def cmd_retention(args) -> None:
    expired = plan_deletions(inventory(), utc_now())
    for item in expired:
        if args.dry_run:
            log(f"(dry-run) حذف می‌شد: {item.path}")
        elif item.kind == "full":
            rclone("purge", f"{REMOTE}/{item.path}")
        else:
            rclone("deletefile", f"{REMOTE}/{item.path}")
    if expired and not args.dry_run:
        log(f"سیاست نگهداری: {len(expired)} بک‌آپ قدیمی حذف شد")


def cmd_list(_args) -> None:
    items = inventory()
    for kind in ("full", "wal", "resumes"):
        group = [item for item in items if item.kind == kind]
        newest = group[-1].created_at.astimezone().strftime("%Y-%m-%d %H:%M") if group else "-"
        print(f"{kind:8} تعداد={len(group):5}  جدیدترین={newest}")
    for item in [item for item in items if item.kind == "full"][-5:]:
        print(f"  {item.path}")


def cmd_restore_resumes(args) -> None:
    """بازیابی فایل‌های رزومه از آخرین بک‌آپ هفتگی (یا آخرین بک‌آپ پیش از --target-time)."""
    target = Path(args.target_dir)
    limit = datetime.fromisoformat(args.target_time) if args.target_time else utc_now()
    candidates = [item for item in inventory() if item.kind == "resumes" and item.created_at <= limit]
    if not candidates:
        sys.exit("هیچ بک‌آپ رزومه‌ای در Offsite وجود ندارد")
    target.mkdir(parents=True, exist_ok=True)
    decrypt_from_remote(candidates[-1].path, consumer=["tar", "-x", "-C", str(target)])
    count = sum(1 for path in (target / "resumes").rglob("*") if path.is_file())
    log(f"✔ {count} فایل رزومه از {candidates[-1].path} در {target}/resumes بازیابی شد")


def cmd_ensure_full(_args) -> None:
    """هنگام راه‌اندازی سرویس: اگر هنوز هیچ بک‌آپ کاملی در Offsite نیست، همین حالا یکی بگیر
    (WAL های ساعتی بدون یک بک‌آپ کامل پایه قابل بازیابی نیستند)."""
    if any(item.kind == "full" for item in inventory()):
        log("بک‌آپ کامل پایه در Offsite موجود است")
        return
    log("هنوز هیچ بک‌آپ کاملی در Offsite نیست — گرفتن اولین بک‌آپ کامل")
    cmd_full(_args)


# ---------------------------------------------------------------------------
# بازیابی (فقط در سرویس backup_restore که کلید خصوصی را دارد)
# ---------------------------------------------------------------------------
RECOVERY_MARKER = "# --- ats-backup recovery settings ---"


def identity() -> str:
    if not Path(IDENTITY_FILE).exists():
        sys.exit(f"کلید خصوصی بازیابی در {IDENTITY_FILE} پیدا نشد")
    return IDENTITY_FILE


def decrypt_from_remote(remote_path: str, consumer: list[str] | None = None, output: Path | None = None) -> None:
    """rclone cat | age -d | zstd -d → consumer (مثلاً tar) یا فایل."""
    commands = [
        ["rclone", "cat", f"{REMOTE}/{remote_path}"],
        ["age", "-d", "-i", identity()],
        ["zstd", "-q", "-d", "-c"],
    ]
    if consumer:
        commands.append(consumer)
    if output is None:
        pipeline(*commands)
        return
    with open(output, "wb") as sink:
        pipeline(*commands, stdout=sink)


def cmd_fetch_wal(args) -> None:
    """restore_command پستگرس. خروج با کد غیرصفر = «این سگمنت وجود ندارد» = پایان WAL های موجود."""
    remote_path = f"wal/{args.segment}.zst.age"
    try:
        if not rclone("lsf", f"{REMOTE}/{remote_path}", capture=True).strip():
            sys.exit(1)
        decrypt_from_remote(remote_path, output=Path(args.destination))
    except (subprocess.CalledProcessError, RuntimeError):
        Path(args.destination).unlink(missing_ok=True)
        sys.exit(1)


def as_postgres(*command: str) -> subprocess.CompletedProcess:
    return subprocess.run(["su-exec", "postgres", *command], check=True, capture_output=True, text=True)


def local_psql(sql: str) -> str:
    """کوئری روی نمونه‌ی بازیابی‌شده (فقط سوکت محلی /tmp، بدون پورت شبکه)."""
    user = os.environ.get("PGUSER", "postgres")
    database = os.environ.get("PGDATABASE", "postgres")
    return as_postgres("psql", "-X", "-h", "/tmp", "-U", user, "-d", database, "-Atc", sql).stdout.strip()


def start_local(data_dir: Path) -> None:
    options = "-c listen_addresses='' -c unix_socket_directories=/tmp -c archive_mode=off"
    as_postgres("pg_ctl", "-D", str(data_dir), "-o", options, "-w", "-t", "3600", "-l", "/tmp/restore.log", "start")


def stop_local(data_dir: Path) -> None:
    as_postgres("pg_ctl", "-D", str(data_dir), "-m", "fast", "-w", "stop")


def recover(data_dir: Path, target_time: str | None) -> float:
    """بک‌آپ کامل مناسب + همه‌ی WAL های بعدش را از Offsite در data_dir بازیابی می‌کند و نمونه را
    تا پایان Recovery (Promote) بالا نگه می‌دارد. خروجی: مدت زمان (ثانیه)."""
    started = time.monotonic()
    if data_dir.exists() and any(data_dir.iterdir()):
        sys.exit(f"پوشه‌ی مقصد {data_dir} خالی نیست")
    data_dir.mkdir(parents=True, exist_ok=True)

    limit = datetime.fromisoformat(target_time) if target_time else utc_now()
    candidates = [item for item in inventory() if item.kind == "full" and item.created_at <= limit]
    if not candidates:
        sys.exit("هیچ بک‌آپ کاملی پیش از زمان هدف در Offsite وجود ندارد")
    base = candidates[-1]
    log(f"۱/۳ دریافت و رمزگشایی بک‌آپ کامل {base.path} از Offsite")
    decrypt_from_remote(f"{base.path}/base.tar.zst.age", consumer=["tar", "-x", "-C", str(data_dir)])

    settings = [
        RECOVERY_MARKER,
        "restore_command = 'ats-backup fetch-wal %f \"%p\"'",
        "recovery_target_action = 'promote'",
    ]
    if target_time:
        settings.append(f"recovery_target_time = '{target_time}'")
    with open(data_dir / "postgresql.auto.conf", "a", encoding="utf-8") as config:
        config.write("\n" + "\n".join(settings) + "\n")
    (data_dir / "recovery.signal").touch()
    subprocess.run(["chown", "-R", "postgres:postgres", str(data_dir)], check=True)
    data_dir.chmod(0o700)

    log("۲/۳ اعمال بک‌آپ‌های افزایشی (WAL) از Offsite" + (f" تا {target_time}" if target_time else " تا آخرین مورد"))
    start_local(data_dir)
    for _ in range(3600):
        if local_psql("select pg_is_in_recovery()") == "f":
            break
        time.sleep(1)
    else:
        raise RuntimeError("Recovery در یک ساعت تمام نشد — /tmp/restore.log را ببینید")
    replayed = local_psql("select pg_walfile_name(pg_current_wal_lsn())")
    log(f"۳/۳ ✔ Recovery کامل شد و دیتابیس Promote شد (آخرین WAL: {replayed})")
    return time.monotonic() - started


def strip_recovery_settings(data_dir: Path) -> None:
    """تنظیمات restore_command را پس از پایان Recovery حذف می‌کند تا postgres_db عادی بالا بیاید."""
    config = data_dir / "postgresql.auto.conf"
    lines = config.read_text(encoding="utf-8").splitlines()
    if RECOVERY_MARKER in lines:
        config.write_text("\n".join(lines[: lines.index(RECOVERY_MARKER)]).rstrip() + "\n", encoding="utf-8")


def cmd_restore_pitr(args) -> None:
    """بازیابی واقعی: خروجی، یک پوشه‌ی داده‌ی سالم و آماده برای سرویس postgres_db است."""
    data_dir = Path(args.target_dir)
    elapsed = recover(data_dir, args.target_time)
    stop_local(data_dir)
    strip_recovery_settings(data_dir)
    log(f"✔ دیتابیس در {data_dir} آماده است ({elapsed:.0f} ثانیه) — حالا postgres_db را روی آن بالا بیاورید")


def cmd_drill(args) -> None:
    """تمرین بازیابی فاجعه: بازیابی کامل از Offsite در یک نمونه‌ی کاملاً جدید و اجرای کوئری بررسی."""
    data_dir = Path(args.target_dir)
    elapsed = recover(data_dir, args.target_time)
    try:
        log(f"✔ زمان بازیابی (RTO) از Offsite تا دیتابیس آماده: {elapsed:.0f} ثانیه")
        print("--- RESULT ---")
        print(local_psql(args.sql))
        print("--- END ---", flush=True)
    finally:
        stop_local(data_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ats-backup", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (
        ("full", cmd_full),
        ("wal", cmd_wal),
        ("resumes", cmd_resumes),
        ("list", cmd_list),
        ("ensure-full", cmd_ensure_full),
    ):
        sub.add_parser(name).set_defaults(func=func)
    retention = sub.add_parser("retention")
    retention.add_argument("--dry-run", action="store_true")
    retention.set_defaults(func=cmd_retention)
    fetch = sub.add_parser("fetch-wal")
    fetch.add_argument("segment")
    fetch.add_argument("destination")
    fetch.set_defaults(func=cmd_fetch_wal)
    for name, func in (("restore-pitr", cmd_restore_pitr), ("drill", cmd_drill)):
        command = sub.add_parser(name)
        command.add_argument("--target-dir", default="/restore/pgdata")
        command.add_argument("--target-time", help="ISO 8601، مثلاً 2026-10-13T10:00:00+03:30 (پیش‌فرض: آخرین لحظه)")
        command.set_defaults(func=func)
    sub.choices["drill"].add_argument("--sql", default="select now()")
    resumes = sub.add_parser("restore-resumes")
    resumes.add_argument("--target-dir", default="/restore/media")
    resumes.add_argument("--target-time")
    resumes.set_defaults(func=cmd_restore_resumes)

    args = parser.parse_args()
    try:
        configure_offsite_credentials()
        args.func(args)
    except (RuntimeError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None)
        log(f"✘ خطا: {error}" + (f"\n{detail}" if detail else ""))
        sys.exit(1)


if __name__ == "__main__":
    main()
