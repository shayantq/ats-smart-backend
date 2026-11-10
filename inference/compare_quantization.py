"""مقایسهٔ جفت‌شدهٔ F16 و Q4 روی همان چهار ورودی؛ فقط موتور بومی اختصاصی آزمایش."""

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from statistics import mean

import httpx

from inference.benchmark import validation_requests
from inference.service import Engine
from training.lora.resources import GIB, check_resources, keep_awake


async def run():
    directory = Path("training/reports/inference")
    report_path = directory / "quality_comparison.json"
    raw_path = directory / "f16_reference.requests.jsonl"
    if report_path.exists() or raw_path.exists():
        raise FileExistsError("شواهد قبلی بازنویسی نمی‌شوند")
    check_resources(directory, starting=True)
    if shutil.disk_usage(".").free < 30 * GIB:
        raise RuntimeError("حداقل ۳۰ GiB فضای آزاد باید حفظ شود")
    q4 = json.loads((directory / "native_q4_quality.json").read_text(encoding="utf-8"))
    rows_q4 = [row for row in q4["rows"] if row["phase"] == "sequential"]
    if len(rows_q4) != 4 or not all(row["valid"] for row in rows_q4):
        raise ValueError("گزارش Q4 کامل نیست")
    os.environ.update(
        INFERENCE_ENGINE="ollama",
        INFERENCE_MODEL="ats-f16",
        INFERENCE_TOKENIZER="models/base-model/tokenizer.json",
    )
    rows = []
    owner = asyncio.current_task()
    running = True

    async def monitor():
        while running:
            try:
                check_resources(directory)
            except RuntimeError:
                owner.cancel("resource_guard")
                return
            await asyncio.sleep(0.5)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:11436", trust_env=False, timeout=60) as http:
        engine = Engine(http=http)
        monitor_task = asyncio.create_task(monitor())
        try:
            async with asyncio.timeout(600):
                await engine.warm()
                for index, request, label in validation_requests(4):
                    check_resources(directory)
                    started = time.perf_counter()
                    output = await engine.analyze(request)
                    row = {
                        "sample": index,
                        "label": label,
                        "score": output.analysis.score,
                        "valid": True,
                        "input_tokens": output.input_tokens,
                        "output_tokens": output.output_tokens,
                        "seconds": time.perf_counter() - started,
                    }
                    rows.append(row)
                    with raw_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(row) + "\n")
                    print(json.dumps(row), flush=True)
                processor = (await http.get("/api/ps")).json()["models"]
        finally:
            running = False
            await monitor_task
            # حتی پس از توقف محافظ، مدل همین آزمایش از حافظه خارج شود.
            try:
                await http.post("/api/generate", json={"model": "ats-f16", "keep_alive": 0}, timeout=5)
            except httpx.HTTPError:
                pass
    if [row["label"] for row in rows] != [row["label"] for row in rows_q4]:
        raise ValueError("ورودی‌های مقایسه همسان نیستند")
    f16_mae = mean(abs(row["score"] - row["label"]) for row in rows)
    q4_mae = mean(abs(row["score"] - row["label"]) for row in rows_q4)
    gate = q4["quantization_quality_gate_declared_before_run"]
    result = {
        "synthetic_validation": True,
        "records": 4,
        "seed": 2026,
        "scope": "Windows native Ollama; quality diagnostic, not container latency or production quality",
        "gate_declared_before_run": gate,
        "f16_mae": f16_mae,
        "q4_mae": q4_mae,
        "mae_increase": q4_mae - f16_mae,
        "full_schema_valid_rate": {"f16": len(rows) / 4, "q4": 1.0},
        "passed": q4_mae - f16_mae <= gate["max_mae_increase_vs_nonquantized"],
        "reference_processor": [{key: model.get(key) for key in ("name", "size", "size_vram")} for model in processor],
        "reference_rows": rows,
    }
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    with keep_awake():
        asyncio.run(run())
