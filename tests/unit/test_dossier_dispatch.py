"""ثبت اتمیک job با نسخهٔ واقعی RQ و Redis ساختگی؛ بدون Worker یا دادهٔ رزومه."""

import asyncio
import uuid

import fakeredis
from rq import Queue

from app.core import queue
from app.tasks.resume_processing import process_resume_task


async def test_atomic_enqueue_under_concurrent_dispatch_does_not_duplicate(monkeypatch):
    connection = fakeredis.FakeRedis()
    task_queue = Queue("synthetic-dispatch", connection=connection)
    monkeypatch.setattr(task_queue, "get_redis_server_version", lambda: (7, 0, 0))
    monkeypatch.setattr(queue, "get_task_queue", lambda name: task_queue)
    claim = str(uuid.uuid4())
    results = await asyncio.gather(
        *(
            queue.enqueue_resume_once(process_resume_task, "synthetic-app", "synthetic.pdf", job_id=claim)
            for _ in range(16)
        )
    )
    assert set(results) == {claim}
    assert task_queue.job_ids == [claim]
    job = task_queue.fetch_job(claim)
    assert job.timeout == 300 and job.retries_left == 2 and job.retry_intervals == [60, 300]
    assert job.description == "resume_reanalysis"


async def test_unknown_redis_result_can_be_reconciled_with_same_claim(monkeypatch):
    connection = fakeredis.FakeRedis()
    task_queue = Queue("synthetic-dispatch", connection=connection)
    monkeypatch.setattr(task_queue, "get_redis_server_version", lambda: (7, 0, 0))
    monkeypatch.setattr(queue, "get_task_queue", lambda name: task_queue)
    claim = str(uuid.uuid4())
    assert await queue.enqueue_resume_once(process_resume_task, "synthetic-app", "synthetic.pdf", job_id=claim) == claim
    # فراخواننده پاسخ قبلی را از دست داده است؛ بازپخش نباید همان شناسه را دوباره صف کند.
    assert await queue.enqueue_resume_once(process_resume_task, "synthetic-app", "synthetic.pdf", job_id=claim) == claim
    assert task_queue.count == 1
