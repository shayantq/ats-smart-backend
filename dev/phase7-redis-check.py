"""آزمون Redis واقعی روی صف اختصاصی؛ هیچ Worker به این صف گوش نمی‌دهد."""

import asyncio
import json
import uuid

from redis import Redis
from rq import Queue
from sqlalchemy.engine import make_url
from app.core.config import settings
from app.core import queue
from app.tasks.resume_processing import process_resume_task


async def main():
    assert make_url(settings.DATABASE_URL).database == "ats_preview", "local database marker required"
    connection = Redis.from_url(settings.REDIS_URL)
    name = "phase7-synthetic-" + uuid.uuid4().hex
    q = Queue(name, connection=connection)
    original = queue.get_task_queue
    queue.get_task_queue = lambda _name: q
    claim = str(uuid.uuid4())
    try:
        result = await asyncio.gather(
            *(
                queue.enqueue_resume_once(process_resume_task, "synthetic-app", "synthetic.pdf", job_id=claim)
                for _ in range(16)
            )
        )
        assert set(result) == {claim} and q.job_ids == [claim]
        print(
            json.dumps(dict(synthetic=True, redis_real=True, concurrent_dispatch=16, queued_jobs=q.count, duplicates=0))
        )
    finally:
        queue.get_task_queue = original
        q.delete(delete_jobs=True)
        connection.close()


if __name__ == "__main__":
    asyncio.run(main())
