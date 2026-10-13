# =============================================================================
# ایمیج سرویس پشتیبان‌گیری و بازیابی فاجعه (backup / backup_restore / offsite_storage محلی)
#
# پایه‌ی postgres:16-alpine: ابزارهای pg_basebackup/pg_dump/pg_ctl دقیقاً هم‌نسخه‌ی سرور
# دیتابیس هستند (لازمه‌ی بک‌آپ فیزیکی و بازیابی لحظه‌ای).
#   age     رمزنگاری با کلید عمومی (سرور فقط کلید عمومی را دارد)
#   zstd    فشرده‌سازی سریع پیش از رمزنگاری
#   rclone  انتقال به هر فضای Offsite (S3/SFTP/...) با بررسی سلامت فایل
# =============================================================================
FROM postgres:16-alpine

RUN apk add --no-cache age rclone zstd tar python3 tzdata

# زمان‌بندی cron (۰۲:۰۰ شبانه و ...) به وقت تهران
ENV TZ=Asia/Tehran \
    WAL_ARCHIVE_DIR=/wal_archive \
    MEDIA_DIR=/media \
    METRICS_DIR=/metrics

COPY ats_backup.py retention.py /opt/ats-backup/
COPY entrypoint.sh /usr/local/bin/ats-backup-entrypoint
COPY crontab /etc/crontabs/root

# اگر فایل‌ها روی ویندوز با CRLF ذخیره شده باشند، اسکریپت‌ها و cron در لینوکس خراب می‌شوند
RUN sed -i 's/\r$//' /opt/ats-backup/*.py /usr/local/bin/ats-backup-entrypoint /etc/crontabs/root \
    && chmod +x /opt/ats-backup/ats_backup.py /usr/local/bin/ats-backup-entrypoint \
    && ln -s /opt/ats-backup/ats_backup.py /usr/local/bin/ats-backup

ENTRYPOINT ["ats-backup-entrypoint"]
CMD ["cron"]
