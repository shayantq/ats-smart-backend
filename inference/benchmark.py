"""سنجش واقعی از کلاینت بک‌اند تا JSON معتبر؛ گزارش فقط عدد دارد، بدون متن رزومه."""

import argparse
import asyncio
import json
import math
import re
import subprocess
import time
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.service_auth import issue_service_token
from app.model_inference.client import InferenceClient, InferenceError
from app.model_inference.contract import AnalyzeRequest, JobContext
from training.lora.data import load_jsonl, stratified_subset
from training.lora.resources import GIB, windows_memory

LEAK_TOLERANCE_MIB = 128
PLATEAU_RANGE_MIB = 128


def validation_requests(size=12):
    return evaluation_requests(size, "validation")


def evaluation_requests(size=100, split="test"):
    if split not in ("validation", "test"):
        raise ValueError("ارزیابی باید از validation یا test باشد")
    records = stratified_subset(load_jsonl(Path("data/finetune") / f"{split}.jsonl"), size, 2026)
    requests = []
    fields = {
        "عنوان": "title",
        "دپارتمان": "department",
        "سطح ارشدیت": "required_seniority",
        "تحصیلات لازم": "required_education",
    }
    for index, record in enumerate(records):
        job, resume = record["input"].split("\n\n## رزومه\n", 1)
        header, separator, description = job.partition("شرح:\n")
        values = {"description": description if separator else None}
        for line in header.splitlines():
            label, _, value = line.partition(": ")
            if label in fields:
                values[fields[label]] = value
            elif label == "مهارت‌های لازم":
                values["skills_required"] = value.split("، ")
        requests.append(
            (index, AnalyzeRequest(resume_text=resume, job=JobContext(**values)), json.loads(record["output"])["score"])
        )
    return requests


def vram():
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return int(result.stdout.strip().splitlines()[0]) if result.returncode == 0 else None


def percentiles(values):
    values = sorted(values)
    return {f"p{p}": values[max(0, math.ceil(p / 100 * len(values)) - 1)] for p in (50, 95, 99)} | {"max": max(values)}


def engine_metadata(kind):
    if kind == "llama_cpp_gpu":
        result = subprocess.run(
            ["docker", "logs", "ats-inference-local-ats-engine-1"], capture_output=True, text=True, timeout=10
        )
        offloads = re.findall(r"^offloaded ([0-9]+)/([0-9]+) layers to GPU$", result.stdout, re.MULTILINE)
        with httpx.Client(base_url="http://127.0.0.1:11435", trust_env=False, timeout=3) as http:
            props = http.get("/props").json()
        return {
            "engine": "llama.cpp:52e53a76d in ollama:0.40.15",
            "quantization": props.get("model_ftype"),
            "model_file": props.get("model_path"),
            "context_tokens": props["default_generation_settings"]["n_ctx"],
            "max_output_tokens": 640,
            "configured_engine_parallel": props["total_slots"],
            "processor_evidence": {"offloaded_layers_and_total": offloads},
            "gpu_inference_observed": bool(offloads) and int(offloads[-1][0]) == int(offloads[-1][1]) > 0,
            "speculation": "ngram-cache; train-only static proposals, every proposal target-verified",
        }
    if kind == "vllm":
        result = subprocess.run(
            ["docker", "logs", "ats-inference-local-ats-engine-1"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # فقط الگوهای عددی startup؛ لاگ خام یا متن احتمالی درخواست وارد گزارش نمی‌شود.
        logs = result.stdout + result.stderr
        weights = re.findall(r"Loading model weights took ([0-9.]+) GB", logs)
        blocks = re.findall(r"# GPU blocks: ([0-9]+)", logs)
        return {
            "engine": "vllm:0.6.6",
            "quantization": "Q4_K_M",
            "context_tokens": 2048,
            "max_output_tokens": 640,
            "configured_engine_parallel": 1,
            "processor_evidence": {"loaded_weight_gb": weights, "gpu_cache_blocks": blocks},
            "gpu_inference_observed": bool(weights) and bool(blocks) and int(blocks[-1]) > 0,
        }
    if kind == "ollama_native":
        with httpx.Client(base_url="http://127.0.0.1:11436", trust_env=False, timeout=5) as client:
            version = client.get("/api/version").json()["version"]
            models = client.get("/api/ps").json()["models"]
        return {
            "engine": "ollama-native:" + version,
            "scope": "Windows GPU staging; gateway in container; GPU engine outside container",
            "processor_evidence": [
                {key: model.get(key) for key in ("name", "size", "size_vram", "details")} for model in models
            ],
            "context_tokens": 2048,
            "max_output_tokens": 640,
            "configured_engine_parallel": 1,
            "gpu_inference_observed": any(model.get("size_vram", 0) > 0 for model in models),
        }
    if kind == "llama_cpp":
        return {
            "engine": "llama.cpp:b11718",
            "quantization": "Q4_K_M",
            "processor_evidence": "compose.cpu.yml: --gpu-layers 0, CPU-only diagnostic",
            "context_tokens": 2048,
            "max_output_tokens": 640,
            "configured_engine_parallel": 1,
            "gpu_inference_observed": False,
        }
    result = subprocess.run(
        ["docker", "compose", "-f", "inference/compose.yml", "exec", "-T", "ats-engine", "ollama", "ps"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return {
        "engine": "ollama:0.40.15",
        "quantization": "Q4_K_M",
        "context_tokens": 2048,
        "max_output_tokens": 640,
        "configured_engine_parallel": 1,
        "processor_evidence": result.stdout.strip() if result.returncode == 0 else "unavailable",
        "gpu_inference_observed": result.returncode == 0 and "GPU" in result.stdout,
    }


async def run(args):
    if args.report.exists():
        raise FileExistsError("گزارش قبلی حفظ می‌شود؛ نام تازه انتخاب کنید")
    settings.SERVICE_NAME = "worker"
    settings.SERVICE_AUTH_PRIVATE_KEY_FILE = str(args.key)
    rows, memory = [], []
    args.report.parent.mkdir(parents=True, exist_ok=True)
    raw_path = args.report.with_suffix(".requests.jsonl")
    if raw_path.exists():
        raise FileExistsError("شواهد خام قبلی بازنویسی نمی‌شوند")
    inputs = validation_requests(args.records)
    started = time.perf_counter()
    running = True
    health_samples = []
    owner = asyncio.current_task()

    async def guard_resources(minimum_gib=2):
        memory_status = windows_memory()
        if memory_status is None or memory_status["commit_available"] >= minimum_gib * GIB:
            return
        args.report.with_suffix(".resource_guard.json").write_text(
            json.dumps(
                {"aborted": True, "commit_available": memory_status["commit_available"], "minimum_gib": minimum_gib}
            ),
            encoding="utf-8",
        )
        if args.engine == "ollama_native":
            # فقط موتور اختصاصی همین آزمایش و نام‌های متعلق به آن؛ سرور عمومی کاربر دست نمی‌خورد.
            try:
                async with httpx.AsyncClient(base_url="http://127.0.0.1:11436", trust_env=False, timeout=3) as native:
                    models = (await native.get("/api/ps")).json()["models"]
                    for model in models:
                        if model["name"].split(":")[0] in ("ats-q4", "ats-f16"):
                            await native.post("/api/generate", json={"model": model["name"], "keep_alive": 0})
            except (httpx.HTTPError, ValueError, KeyError):
                pass
        raise MemoryError("توقف محافظ حافظه؛ شواهد خام حفظ شدند")

    await guard_resources(2.5)
    # درخواست‌های سنجش فقط پس از آماده‌شدن سرویس ارسال شوند؛ این زمان cold start نیست.
    async with httpx.AsyncClient(trust_env=False, timeout=2) as readiness:
        async with asyncio.timeout(120):
            while True:
                try:
                    if (await readiness.get(args.url + "/ready")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)

    async def monitor():
        async with httpx.AsyncClient(trust_env=False, timeout=2) as health:
            while running:
                try:
                    await guard_resources()
                except MemoryError:
                    owner.cancel("resource_guard")
                    return
                memory.append({"seconds": time.perf_counter() - started, "mib": await asyncio.to_thread(vram)})
                before = time.perf_counter()
                try:
                    result = await health.get(args.url + "/health")
                    status = result.status_code
                except httpx.HTTPError:
                    status = 0
                health_samples.append({"status": status, "seconds": time.perf_counter() - before})
                await asyncio.sleep(1)

    async with InferenceClient(
        args.url,
        lambda: issue_service_token(audience="ats-inference"),
        timeout=90,
        active=args.client_active,
        waiting=args.client_waiting,
    ) as client:

        async def one(item, phase):
            index, request, label = item
            before = time.perf_counter()
            row = {"sample": index, "phase": phase, "label": label}
            try:
                output = await client.analyze(request)
                row.update(
                    valid=True,
                    input_tokens=output.input_tokens,
                    output_tokens=output.output_tokens,
                    score=output.analysis.score,
                    hr_outcome_cleared=output.analysis.hr_outcome is None,
                )
            except InferenceError as error:
                row.update(valid=False, error=error.code, status=error.status_code)
            row["seconds"] = time.perf_counter() - before
            rows.append(row)
            with raw_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            print(json.dumps(row), flush=True)

        # اولین درخواست جداست؛ نتیجهٔ آن وارد آمار گرم نمی‌شود.
        await one(inputs[0], "first_request")
        metadata = await asyncio.to_thread(engine_metadata, args.engine)
        baseline = await asyncio.to_thread(vram)
        initial_baseline = baseline
        warm_baseline_seconds = time.perf_counter() - started
        task = asyncio.create_task(monitor())
        try:
            async with asyncio.timeout(1200):
                for item in inputs:
                    await one(item, "sequential")
                # بعد از یک گذر کاملِ ورودی‌های متنوع، cache های مجاز در baseline گرم قرار دارند.
                baseline = await asyncio.to_thread(vram)
                warm_baseline_seconds = time.perf_counter() - started
                for concurrency in () if args.quality_only else (2, 4):
                    for offset in range(0, len(inputs), concurrency):
                        await asyncio.gather(
                            *(one(item, f"concurrent_{concurrency}") for item in inputs[offset : offset + concurrency])
                        )
                # فشار بیش از ظرفیت و لغو؛ همان موتور زنده باقی می‌ماند.
                if not args.quality_only:
                    await asyncio.gather(*(one(inputs[i % len(inputs)], "overload") for i in range(16)))
                    cancelled = asyncio.create_task(client.analyze(inputs[-1][1]))
                    await asyncio.sleep(0.25)
                    cancelled.cancel()
                    await asyncio.gather(cancelled, return_exceptions=True)
                    await asyncio.sleep(5)
                    await one(inputs[1], "after_cancel")
                    await asyncio.sleep(5)
        finally:
            running = False
            await task
    post = await asyncio.to_thread(vram)
    summaries = {}
    for phase in ("sequential", "concurrent_2", "concurrent_4", "overload"):
        group = [r for r in rows if r["phase"] == phase]
        successes = [r["seconds"] for r in group if r["valid"]]
        summaries[phase] = {
            "attempts": len(group),
            "failures": sum(not r["valid"] for r in group),
            "latency_seconds": percentiles(successes) if successes else None,
            "all_complete_under_3_seconds": bool(group) and all(r["valid"] and r["seconds"] < 3 for r in group),
        }
    samples = [r["mib"] for r in memory if r["mib"] is not None]
    tail = samples[-10:]
    report = {
        "data": "synthetic_validation_only",
        "seed": 2026,
        "records": args.records,
        "quality_only": args.quality_only,
        "client_capacity": {"active": args.client_active, "waiting": args.client_waiting},
        "runtime": metadata,
        "quantization_quality_gate_declared_before_run": {
            "same_fixed_validation_inputs": True,
            "required_valid_rate": 1.0,
            "max_mae_increase_vs_nonquantized": 2.0,
            "note": "small synthetic diagnostic; not real-world quality acceptance",
        },
        "cold_start": {
            "measured": False,
            "note": "first_request recorded separately; not a measured container startup",
        },
        "summaries": summaries,
        "rows": rows,
        "health_during_generation": {
            "requests": len(health_samples),
            "failures": sum(row["status"] != 200 for row in health_samples),
            "latency_seconds": percentiles([row["seconds"] for row in health_samples]) if health_samples else None,
        },
        "vram": {
            "gpu_container_acceptance_eligible": args.engine in ("ollama", "vllm", "llama_cpp_gpu"),
            "scope": "whole_GPU_including_desktop",
            "tolerance_mib_declared_before_run": LEAK_TOLERANCE_MIB,
            "plateau_range_tolerance_mib": PLATEAU_RANGE_MIB,
            "warm_baseline_mib": baseline,
            "initial_after_first_request_mib": initial_baseline,
            "warm_baseline_seconds": warm_baseline_seconds,
            "baseline_protocol": "after one full fixed sequential validation pass; no restart",
            "peak_mib": max(samples) if samples else None,
            "post_drain_mib": post,
            "bounded_soak_passed": args.engine in ("ollama", "vllm", "llama_cpp_gpu")
            and metadata["gpu_inference_observed"]
            and not args.quality_only
            and len([r for r in rows if r["valid"]]) >= args.records * 3
            and len([r for r in rows if r["valid"] and r["phase"] not in ("first_request", "sequential")])
            >= args.records * 2
            and bool(tail)
            and post - baseline <= LEAK_TOLERANCE_MIB
            and max(tail) - min(tail) <= PLATEAU_RANGE_MIB,
            "samples": memory,
        },
    }
    async with httpx.AsyncClient(trust_env=False) as http:
        report["health_after_soak"] = (await http.get(args.url + "/health")).status_code
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--key", type=Path, default=Path("secrets/inference/worker.pem"))
    parser.add_argument("--records", type=int, default=12, choices=range(4, 25))
    parser.add_argument("--quality-only", action="store_true")
    parser.add_argument(
        "--engine", choices=["ollama", "ollama_native", "llama_cpp", "vllm", "llama_cpp_gpu"], default="ollama"
    )
    parser.add_argument("--client-active", type=int, choices=range(1, 17), default=4)
    parser.add_argument("--client-waiting", type=int, choices=range(0, 17), default=8)
    parser.add_argument("--report", type=Path, default=Path("training/reports/inference/benchmark.json"))
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
