"""ارزیابی جفت‌شدهٔ ۱۰۰ نمونه؛ متن‌ها ذخیره نمی‌شوند و نتیجه کیفیت واقعی ATS نیست."""

import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
import random
import time
import unicodedata

import httpx

from app.core.config import settings
from app.core.service_auth import issue_service_token
from app.model_inference.client import InferenceClient, InferenceError
from inference.benchmark import evaluation_requests, percentiles
from training.lora.resources import GIB, windows_memory


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def words(values):
    return sorted({digest(unicodedata.normalize("NFKC", value).casefold().strip()) for value in values})


def jaccard(left, right):
    left, right = set(left), set(right)
    return len(left & right) / len(left | right) if left | right else 1.0


async def run(args):
    if args.report.exists():
        raise FileExistsError("گزارش قبلی حفظ می‌شود")
    if args.report.with_suffix(".requests.jsonl").exists():
        raise FileExistsError("شواهد خام قبلی حفظ می‌شوند")
    settings.SERVICE_NAME = "worker"
    settings.SERVICE_AUTH_PRIVATE_KEY_FILE = "secrets/inference/worker.pem"
    rows = []
    async with httpx.AsyncClient(trust_env=False, timeout=3) as http:
        async with asyncio.timeout(180):
            while True:
                try:
                    if (await http.get("http://127.0.0.1:8081/ready")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
    async with InferenceClient(
        "http://127.0.0.1:8081", lambda: issue_service_token(audience="ats-inference"), active=1, waiting=0, timeout=60
    ) as client:
        for index, request, label in evaluation_requests(100, "test"):
            memory = windows_memory()
            if memory and memory["commit_available"] < 2 * GIB:
                raise MemoryError("محافظ حافظه؛ شواهد خام حفظ شدند")
            row = {"index": index, "label": label, "request_sha256": digest(request.model_dump())}
            started = time.perf_counter()
            try:
                response = await client.analyze(request)
                value = response.analysis
                row.update(
                    valid=True,
                    score=value.score,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    verdict=digest(value.verdict),
                    matched=words(value.matched_skills),
                    missing=words(value.missing_skills),
                    flags=sorted({digest((flag.code, flag.severity)) for flag in value.flags}),
                    rationale=digest(value.rationale),
                    experience_years=value.experience.total_years,
                    analysis=digest(value.model_dump()),
                    hr_outcome_is_null=value.hr_outcome is None,
                )
            except InferenceError as error:
                row.update(valid=False, status=error.status_code, error=error.code)
            row["seconds"] = time.perf_counter() - started
            rows.append(row)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.with_suffix(".requests.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            if (index + 1) % 10 == 0:
                print(json.dumps({"completed": index + 1, "valid": sum(r["valid"] for r in rows)}), flush=True)
    valid = [r for r in rows if r["valid"]]
    report = {
        "name": args.name,
        "split": "test",
        "synthetic": True,
        "seed": 2026,
        "records": len(rows),
        "dataset_sha256": hashlib.sha256(Path("data/finetune/test.jsonl").read_bytes()).hexdigest(),
        "valid_rate": len(valid) / len(rows),
        "rows": rows,
        "mae": sum(abs(r["score"] - r["label"]) for r in valid) / len(valid) if valid else None,
        "latency": percentiles([r["seconds"] for r in valid]) if valid else None,
        "all_valid_and_under_3": len(valid) == len(rows) and all(r["seconds"] < 3 for r in valid),
    }
    if args.reference:
        reference = json.loads(args.reference.read_text(encoding="utf-8"))
        if reference["dataset_sha256"] != report["dataset_sha256"] or len(reference["rows"]) != len(rows):
            raise ValueError("مجموعهٔ مرجع تغییر کرده است")
        pairs = list(zip(reference["rows"], rows))
        if any(a["request_sha256"] != b["request_sha256"] for a, b in pairs):
            raise ValueError("ورودی‌های مرجع و نامزد یکسان نیستند")
        complete = all(a["valid"] and b["valid"] for a, b in pairs)
        if complete:
            deltas = [abs(b["score"] - b["label"]) - abs(a["score"] - a["label"]) for a, b in pairs]
            rng = random.Random(2026)
            boot = sorted(sum(rng.choices(deltas, k=len(deltas))) / len(deltas) for _ in range(5000))
            report["paired"] = {
                "reference_name": reference["name"],
                "reference_is_same_quantized_model_not_F16": True,
                "score_agreement": sum(a["score"] == b["score"] for a, b in pairs) / len(pairs),
                "verdict_agreement": sum(a["verdict"] == b["verdict"] for a, b in pairs) / len(pairs),
                "matched_jaccard": sum(jaccard(a["matched"], b["matched"]) for a, b in pairs) / len(pairs),
                "missing_jaccard": sum(jaccard(a["missing"], b["missing"]) for a, b in pairs) / len(pairs),
                "flags_jaccard": sum(jaccard(a["flags"], b["flags"]) for a, b in pairs) / len(pairs),
                "mae_delta": sum(deltas) / len(deltas),
                "mae_delta_bootstrap_95_ci": [
                    boot[math.ceil(0.025 * len(boot)) - 1],
                    boot[math.ceil(0.975 * len(boot)) - 1],
                ],
                "declared_max_mae_increase": 2.0,
                "score_gate_passed": boot[math.ceil(0.975 * len(boot)) - 1] <= 2,
            }
        else:
            report["paired"] = {"complete": False, "score_gate_passed": False}
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    asyncio.run(run(parser.parse_args()))
