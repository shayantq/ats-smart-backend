"""مقایسهٔ محدود inference تکی و دسته‌ای روی validation ساختگی؛ بدون مصرف test."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from training.lora.config import resolve_base_model
from training.lora.data import load_jsonl, stratified_subset
from training.lora.evaluate import MAX_NEW_TOKENS, _generate, _load, parse_score
from training.lora.resources import check_resources, keep_awake


def run(adapter: Path, report_path: Path) -> dict:
    import torch

    if report_path.exists():
        raise ValueError("گزارش قبلی بازنویسی نمی‌شود؛ مسیر تازه انتخاب کنید")
    check_resources(report_path.parent, starting=True)
    records = stratified_subset(load_jsonl(Path("data/finetune/validation.jsonl")), 4, 2026)
    tokenizer, model = _load(resolve_base_model(None), adapter)
    results, references = [], None
    deadline = time.monotonic() + 600
    for batch_size in (1, 4):
        if time.monotonic() >= deadline:
            raise TimeoutError("مهلت ده‌دقیقه‌ای بنچمارک inference تمام شد")
        check_resources(report_path.parent)
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        started = time.perf_counter()
        texts = _generate(tokenizer, model, records, batch_size)
        torch.cuda.synchronize()
        seconds = time.perf_counter() - started
        parsed = [parse_score(text) for text in texts]
        row = {
            "batch_size": batch_size,
            "seconds": round(seconds, 3),
            "seconds_per_record": round(seconds / len(records), 3),
            "peak_allocated_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
            "peak_reserved_gib": round(torch.cuda.max_memory_reserved() / 1024**3, 3),
            "valid_json_count": sum(ok for ok, _ in parsed),
            "valid_score_count": sum(score is not None for _, score in parsed),
            "generated_tokens": [len(tokenizer.encode(text, add_special_tokens=False)) for text in texts],
        }
        if references is None:
            references = texts
        else:
            row["exact_text_matches"] = sum(text == ref for text, ref in zip(texts, references))
            row["parsed_scores_match"] = parsed == [parse_score(text) for text in references]
        results.append(row)
        print(json.dumps(row), flush=True)
    report = {
        "run_kind": "validation_inference_microbenchmark",
        "synthetic_data": True,
        "heldout_test_used": False,
        "final_acceptance": False,
        "records": len(records),
        "max_new_tokens": MAX_NEW_TOKENS,
        "adapter_reloaded": True,
        "measurements": results,
        "batched_speedup": round(results[0]["seconds"] / results[1]["seconds"], 3),
        "estimated_200_record_hours": round(results[1]["seconds_per_record"] * 200 / 3600, 3),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    run(args.adapter, args.report)
    return 0


if __name__ == "__main__":
    with keep_awake():
        raise SystemExit(main())
