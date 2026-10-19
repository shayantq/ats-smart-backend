"""
کار پس‌زمینه‌ی تولید بانک سؤال مصاحبه (صف «genai» — بنگرید app/core/queue.py و app/genai/service.py).

مثل پردازش رزومه، هر کار با asyncio.run() یک event loop تازه و اتصال دیتابیس مخصوص همان loop دارد
(worker_session_factory) — Pool مشترک برنامه بین loop ها جابه‌جا نمی‌شود.
"""

import asyncio
import uuid

from app.db.session import worker_session_factory
from app.genai.service import run_question_set_job


def generate_interview_questions_task(question_set_id: str) -> None:
    asyncio.run(_run(uuid.UUID(question_set_id)))


async def _run(question_set_id: uuid.UUID) -> None:
    async with worker_session_factory() as session_factory:
        await run_question_set_job(question_set_id, session_factory)
