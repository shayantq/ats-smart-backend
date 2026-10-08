"""
تست متریک‌های Prometheus (app/core/metrics.py) — پایه‌ی داشبورد RPS/Latency و
هشدار نرخ خطای بالای ۵٪.
"""

import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _counter_value(metrics_text: str, route: str, status: str) -> float:
    pattern = rf'^http_requests_total\{{method="GET",route="{re.escape(route)}",status="{status}"\}} (\S+)$'
    match = re.search(pattern, metrics_text, re.MULTILINE)
    return float(match.group(1)) if match else 0.0


@pytest.mark.asyncio
async def test_requests_are_counted_by_route_template_not_raw_path():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = (await client.get("/metrics")).text
        await client.get("/api/v1/health")
        await client.get("/this/path/does/not/exist")
        # یک مسیر با پارامتر: برچسب باید الگوی مسیر باشد، نه UUID واقعی (جلوگیری از انفجار Cardinality)
        await client.get("/api/v1/interviews/7f1d2c3e-0000-4000-8000-000000000000")
        after = (await client.get("/metrics")).text

    assert _counter_value(after, "/api/v1/health", "200") == _counter_value(before, "/api/v1/health", "200") + 1
    assert _counter_value(after, "unmatched", "404") == _counter_value(before, "unmatched", "404") + 1
    assert 'route="/api/v1/interviews/{interview_id}"' in after
    assert "7f1d2c3e-0000-4000-8000-000000000000" not in after
    # خودِ /metrics شمرده نمی‌شود
    assert 'route="/metrics"' not in after
    assert "http_request_duration_seconds_bucket" in after
