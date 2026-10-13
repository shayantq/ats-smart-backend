"""تست واحد سیاست تلاش مجدد صف (app/core/queue.py): ایمیل‌ها در خطای گذرای SMTP از دست نروند."""

import pytest

from app.core import queue
from app.tasks.notifications import send_otp_email_task


class _FakeJob:
    id = "job-1"


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func, *args, **kwargs):
        self.calls.append((func, args, kwargs))
        return _FakeJob()


def _process_resume(resume_id):  # کار غیر ایمیلی نمونه
    return resume_id


@pytest.fixture
def fake_queue(monkeypatch):
    fake = _FakeQueue()
    monkeypatch.setattr(queue, "get_task_queue", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_email_tasks_are_retried_with_backoff(fake_queue):
    job_id = await queue.enqueue_task(send_otp_email_task, "user@example.com", "123456", 10)

    assert job_id == "job-1"
    _, args, kwargs = fake_queue.calls[0]
    assert args == ("user@example.com", "123456", 10)
    retry = kwargs["retry"]
    assert retry.max == 3
    assert retry.intervals == [30, 120, 600]


@pytest.mark.asyncio
async def test_other_tasks_are_not_retried_by_default(fake_queue):
    await queue.enqueue_task(_process_resume, "resume-1")

    assert "retry" not in fake_queue.calls[0][2]


@pytest.mark.asyncio
async def test_explicit_retry_is_respected(fake_queue):
    await queue.enqueue_task(send_otp_email_task, "user@example.com", "1", 10, retry=None)

    assert fake_queue.calls[0][2]["retry"] is None
