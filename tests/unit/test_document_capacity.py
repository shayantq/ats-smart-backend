"""قطع درخواست نباید پیش از پایان رندر ظرفیت واقعی را آزاد کند."""

import asyncio
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Response

from app.routers import applications


async def test_cancelled_preview_holds_capacity_until_render_finishes(monkeypatch):
    slots = asyncio.Semaphore(1)
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(applications, "_preview_slots", slots)
    monkeypatch.setattr(
        applications, "get_application_dossier", AsyncMock(return_value=SimpleNamespace(resume_id=uuid.uuid4()))
    )

    def render(*args):
        started.set()
        assert release.wait(2)
        return {"page": 1}

    monkeypatch.setattr(applications, "render_document_page", render)
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(file_url="synthetic.pdf"))
        )
    )
    task = asyncio.create_task(applications.application_document_page(uuid.uuid4(), Response(), 1, None, db))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert slots.locked()
        with pytest.raises(HTTPException) as error:
            await applications.application_document_page(uuid.uuid4(), Response(), 1, None, db)
        assert error.value.status_code == 429
    finally:
        release.set()
        async with asyncio.timeout(2):
            while slots.locked():
                await asyncio.sleep(0.01)
