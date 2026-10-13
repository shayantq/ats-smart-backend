#!/bin/sh
# نقطه‌ی ورود ایمیج بک‌آپ — یک ایمیج، سه نقش:
#   cron            سرویس backup: زمان‌بندی خودکار بک‌آپ‌ها (backup/crontab)
#   serve-offsite   سرویس offsite_storage: شبیه‌ساز سرور Offsite در محیط لوکال (SFTP)
#   <هر دستور دیگر>  اجرای مستقیم ats-backup (مثلاً drill یا restore-pitr در backup_restore)
set -eu

case "${1:-cron}" in
    cron)
        # پوشه‌ی آرشیو WAL: postgres (uid 70) می‌نویسد، این سرویس رمزنگاری و منتقل و حذف می‌کند
        install -d -o 70 -g 70 -m 700 "${WAL_ARCHIVE_DIR}"
        # crond متغیرهای محیطی کانتینر را به کارها نمی‌دهد؛ هر کار در crontab این فایل را می‌خواند
        (umask 077 && export -p > /etc/ats-backup.env)
        # اگر هنوز هیچ بک‌آپ کاملی در Offsite نیست (اولین راه‌اندازی)، همین حالا یکی گرفته شود
        ats-backup ensure-full || echo "[ats-backup] ensure-full ناموفق بود؛ در اجرای زمان‌بندی‌شده‌ی بعدی دوباره تلاش می‌شود"
        echo "[ats-backup] زمان‌بندی فعال شد ($(date '+%Y-%m-%d %H:%M %Z')):"
        grep -v '^#' /etc/crontabs/root | grep -v '^$'
        exec crond -f -l 6
        ;;
    serve-offsite)
        exec rclone serve sftp /data --addr :2022 \
            --user "${OFFSITE_SFTP_USER}" --pass "${OFFSITE_SFTP_PASSWORD}"
        ;;
    *)
        # کلید خصوصی بازیابی باید برای پردازه‌ی postgres (restore_command) هم خوانا باشد
        if [ -f "${BACKUP_AGE_IDENTITY_FILE:-}" ]; then
            install -o postgres -g postgres -m 400 "${BACKUP_AGE_IDENTITY_FILE}" /tmp/age-identity.txt
            export BACKUP_AGE_IDENTITY_FILE=/tmp/age-identity.txt
        fi
        exec ats-backup "$@"
        ;;
esac
