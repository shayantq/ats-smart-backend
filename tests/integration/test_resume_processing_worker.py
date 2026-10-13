"""
تست رگرسیون یافته‌ی بازبینی Staging: Worker هر کار پردازش رزومه را با asyncio.run() در یک
event loop تازه اجرا می‌کند. وقتی کارها از Connection Pool مشترک برنامه استفاده می‌کردند، اتصال‌های
باقی‌مانده از loop کار قبلی در کار بعدی با «attached to a different loop» شکست می‌خوردند —
یعنی هر Worker فقط اولین رزومه را پردازش می‌کرد (۴۴۹۴ کار ناموفق در FailedJobRegistry).
"""

import logging

from app.core.config import settings
from app.tasks import resume_processing


def test_consecutive_resume_jobs_in_same_worker_process_all_reach_database(test_database_url, monkeypatch, caplog):
    monkeypatch.setattr(settings, "DATABASE_URL", test_database_url)
    # مراحل سنگین (OCR/NER) در این تست مهم نیستند؛ فقط دسترسی هر کار به دیتابیس
    monkeypatch.setattr(resume_processing, "_download_file", lambda file_url: b"%PDF-fake")
    monkeypatch.setattr(resume_processing, "extract_raw_text", lambda data, filename: "Python developer")
    monkeypatch.setattr(resume_processing, "run_skill_engine", lambda text, experience: {})

    with caplog.at_level(logging.ERROR, logger=resume_processing.logger.name):
        for index in range(3):  # سه کار پشت‌سرهم در همان پردازه، مثل Worker واقعی
            resume_processing.process_resume_task(
                "00000000-0000-0000-0000-000000000000", f"http://test/media/resumes/missing-{index}.pdf"
            )

    # هر سه کار تا کوئری دیتابیس رسیده‌اند (رکوردی با این file_url وجود ندارد) — بدون خطای event loop
    lookups = [record for record in caplog.records if "رکورد رزومه متناظر" in record.getMessage()]
    assert len(lookups) == 3
