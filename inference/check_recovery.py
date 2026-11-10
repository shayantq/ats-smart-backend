"""بازآزمایی واقعی فشار، لغو و بازیابی صف؛ بدون restart موتور بین درخواست‌ها."""

import asyncio
import argparse
import json
import time
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.service_auth import issue_service_token
from app.model_inference.client import InferenceClient, InferenceError
from inference.benchmark import engine_metadata, validation_requests


async def run(report_path):
    if report_path.exists():
        raise FileExistsError("گزارش قبلی حفظ می‌شود")
    settings.SERVICE_NAME = "worker"
    settings.SERVICE_AUTH_PRIVATE_KEY_FILE = "secrets/inference/worker.pem"
    request = validation_requests(4)[1][1]
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8081", trust_env=False, timeout=3) as health:
        async with InferenceClient(
            "http://127.0.0.1:8081",
            lambda: issue_service_token(audience="ats-inference"),
            active=8,
            waiting=0,
            timeout=90,
        ) as client:
            tasks = [asyncio.create_task(client.analyze(request)) for _ in range(8)]
            await asyncio.sleep(0.5)
            before = (await health.get("/ready")).json()["inflight"]
            for task in tasks:
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            drain_started = time.perf_counter()
            after = before
            for _ in range(20):
                after = (await health.get("/ready")).json()["inflight"]
                if after == 0:
                    break
                await asyncio.sleep(0.1)
            drain_seconds = time.perf_counter() - drain_started
            started = time.perf_counter()
            try:
                output = await client.analyze(request)
                followup = {"valid": True, "input_tokens": output.input_tokens, "output_tokens": output.output_tokens}
            except InferenceError as error:
                followup = {"valid": False, "status": error.status_code, "error": error.code}
            followup["seconds"] = time.perf_counter() - started
            final = (await health.get("/ready")).json()["inflight"]
    report = {
        "runtime": await asyncio.to_thread(engine_metadata, "ollama"),
        "synthetic_validation": True,
        "simultaneous_requests": 8,
        "inflight_before_cancel": before,
        "inflight_after_cancel": after,
        "inflight_final": final,
        "drain_seconds": drain_seconds,
        "overload_429": sum(isinstance(r, InferenceError) and r.status_code == 429 for r in results),
        "cancelled": sum(isinstance(r, asyncio.CancelledError) for r in results),
        "followup": followup,
        "passed": after == 0 and final == 0 and followup["valid"],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("training/reports/inference/gpu_recovery.json"))
    asyncio.run(run(parser.parse_args().report))
