"""تست واحد سیاست صف‌ها (app/core/queue.py): صف درست برای هر کار، تلاش مجدد، Timeout و افزودن انبوه."""

import pytest

from app.core import queue
from app.tasks.notifications import send_otp_email_task, send_status_update_email_task
from app.tasks.resume_processing import process_resume_task


class _FakeJob:
    id = "job-1"


class _FakeQueue:
    def __init__(self, name):
        self.name = name
        self.calls = []
        self.bulk_batches = []

    def enqueue(self, func, *args, **kwargs):
        self.calls.append((func, args, kwargs))
        return _FakeJob()

    def enqueue_many(self, jobs_data):
        self.bulk_batches.append(jobs_data)
        return [_FakeJob() for _ in jobs_data]


def _misc_task(item_id):  # کار عمومی نمونه (نه ایمیل، نه رزومه)
    return item_id


@pytest.fixture
def fake_queues(monkeypatch):
    queues: dict[str, _FakeQueue] = {}
    monkeypatch.setattr(queue, "get_task_queue", lambda name="default": queues.setdefault(name, _FakeQueue(name)))
    return queues


@pytest.mark.asyncio
async def test_email_tasks_go_to_priority_queue_and_are_retried_with_backoff(fake_queues):
    job_id = await queue.enqueue_task(send_otp_email_task, "user@example.com", "123456", 10)

    assert job_id == "job-1"
    _, args, kwargs = fake_queues[queue.QUEUE_NOTIFICATIONS].calls[0]
    assert args == ("user@example.com", "123456", 10)
    assert kwargs["retry"].max == 3
    assert kwargs["retry"].intervals == [30, 120, 600]
    assert kwargs["job_timeout"] == 120


@pytest.mark.asyncio
async def test_heavy_resume_processing_has_its_own_queue_and_longer_timeout(fake_queues):
    await queue.enqueue_task(process_resume_task, "application-1", "http://media/cv.pdf")

    _, _, kwargs = fake_queues[queue.QUEUE_RESUMES].calls[0]
    assert kwargs["job_timeout"] == 300
    # Worker ازکارافتاده وسط OCR = کار «رهاشده»؛ با همین سیاست دوباره در صف قرار می‌گیرد، نه حذف
    assert kwargs["retry"].max == 2
    assert queue.QUEUE_NOTIFICATIONS not in fake_queues


@pytest.mark.asyncio
async def test_every_job_has_bounded_result_ttl_and_kept_failures(fake_queues):
    await queue.enqueue_task(_misc_task, "item-1")

    _, _, kwargs = fake_queues[queue.QUEUE_DEFAULT].calls[0]
    assert kwargs["result_ttl"] == queue.RESULT_TTL_SECONDS
    assert kwargs["failure_ttl"] == queue.FAILURE_TTL_SECONDS
    assert kwargs["retry"] is not None


@pytest.mark.asyncio
async def test_explicit_retry_is_respected(fake_queues):
    await queue.enqueue_task(send_otp_email_task, "user@example.com", "1", 10, retry=None)

    assert fake_queues[queue.QUEUE_NOTIFICATIONS].calls[0][2]["retry"] is None


@pytest.mark.asyncio
async def test_bulk_emails_are_enqueued_in_pipelined_chunks_on_low_priority_queue(fake_queues):
    recipients = [(f"user{i}@example.com", f"کارجو {i}", "برنامه‌نویس", "Screening") for i in range(1200)]

    count = await queue.enqueue_bulk(send_status_update_email_task, recipients)

    assert count == 1200
    bulk_queue = fake_queues[queue.QUEUE_BULK]
    assert [len(batch) for batch in bulk_queue.bulk_batches] == [500, 500, 200]
    first_job = bulk_queue.bulk_batches[0][0]
    assert first_job.args == recipients[0]
    assert first_job.retry.max == 3
    assert first_job.timeout == 120


@pytest.mark.asyncio
async def test_enqueue_failure_never_breaks_the_request(monkeypatch):
    def broken_queue(name="default"):
        raise ConnectionError("Redis down")

    monkeypatch.setattr(queue, "get_task_queue", broken_queue)

    assert await queue.enqueue_task(send_otp_email_task, "user@example.com", "1", 10) is None
    assert await queue.enqueue_bulk(send_otp_email_task, [("a@example.com", "1", 10)]) == 0


def test_worker_queue_priority_puts_transactional_emails_first():
    assert queue.ALL_QUEUES[0] == queue.QUEUE_NOTIFICATIONS
    assert queue.ALL_QUEUES.index(queue.QUEUE_BULK) > queue.ALL_QUEUES.index(queue.QUEUE_NOTIFICATIONS)
