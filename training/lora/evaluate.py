"""
ارزیابی آداپتر LoRA پس از آموزش، در یک پردازه‌ی تازه (مدل پایه‌ی ۴ بیتی + آداپتر ذخیره‌شده):

    python -m training.lora.evaluate --adapter training/outputs/<run>/adapter --limit 200

برای زیرمجموعه‌ی ثابت test.jsonl پاسخ تولید می‌شود (greedy، قطعی)، JSON پاسخ تجزیه و نمره‌ی score با برچسب
مقایسه می‌شود: نرخ JSON معتبر، نرخ نمره‌ی معتبر (عدد صحیح 0-100) و MAE. برای مقایسه، MAE پیش‌بینی ثابت
(میانگین نمره‌ی train) هم گزارش می‌شود. اندازه‌ی فایل‌های آداپتر در برابر مدل پایه هم ثبت می‌شود.
خروجی: training/reports/<run>/evaluation.json — فقط عدد، بدون متن رکوردها.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean

from training.lora.config import resolve_base_model
from training.lora.data import load_jsonl, prompt_ids, record_score, stratified_subset
from training.lora.resources import keep_awake

DEFAULT_LIMIT = 200
DEFAULT_BATCH = 1
MAX_NEW_TOKENS = 640
SUBSET_SEED = 2026
SHOW_EXAMPLES = 3


def parse_score(text: str) -> tuple[bool, int | None]:
    """(JSON معتبر؟، نمره‌ی صحیح 0-100 یا None)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return False, None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return False, None
    score = payload.get("score") if isinstance(payload, dict) else None
    valid = isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100
    return True, score if valid else None


def summarize(labels: list[int], predictions: list[tuple[bool, int | None]], baseline: float) -> dict:
    if not labels or len(labels) != len(predictions):
        raise ValueError("برچسب‌ها و پیش‌بینی‌ها باید غیرخالی و هم‌اندازه باشند")
    valid = [(label, score) for label, (_, score) in zip(labels, predictions) if score is not None]
    return {
        "records": len(labels),
        "valid_json_rate": round(sum(ok for ok, _ in predictions) / len(labels), 4),
        "valid_score_rate": round(len(valid) / len(labels), 4),
        "mae": round(mean(abs(label - score) for label, score in valid), 2) if valid else None,
        "baseline_constant_mae": round(mean(abs(label - baseline) for label in labels), 2),
        "baseline_constant_value": round(baseline, 2),
    }


def file_sizes_mb(directory: Path, pattern: str) -> dict[str, float]:
    return {path.name: round(path.stat().st_size / 1024**2, 2) for path in sorted(directory.glob(pattern))}


def _load(base_model: str, adapter: Path):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    tokenizer = AutoTokenizer.from_pretrained(adapter)
    tokenizer.padding_side = "left"
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base_model, quantization_config=quantization, dtype=torch.bfloat16, device_map={"": 0}
    )
    model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return tokenizer, model


def _generate(tokenizer, model, records: list[dict], batch_size: int) -> list[str]:
    import torch

    outputs = []
    for start in range(0, len(records), batch_size):
        prompts = [{"input_ids": prompt_ids(tokenizer, record)} for record in records[start : start + batch_size]]
        batch = tokenizer.pad(prompts, return_tensors="pt").to(model.device)
        with torch.no_grad():
            generated = model.generate(
                **batch, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, pad_token_id=tokenizer.pad_token_id
            )
        new_tokens = generated[:, batch["input_ids"].shape[1] :]
        outputs += tokenizer.batch_decode(new_tokens, skip_special_tokens=True)
        print(f"generated {min(start + batch_size, len(records))}/{len(records)}", flush=True)
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m training.lora.evaluate")
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--base-model", default=None)
    parser.add_argument("--data-dir", type=Path, default=Path("data/finetune"))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--report", type=Path, required=True, help="evaluation.json")
    args = parser.parse_args(argv)
    if args.limit <= 0 or args.batch_size <= 0:
        parser.error("limit و batch-size باید مثبت باشند")
    base_model = resolve_base_model(args.base_model)
    if not base_model or not (args.adapter / "adapter_config.json").is_file():
        parser.error("مدل پایه و پوشه‌ی آداپتر معتبر لازم است")
    records = stratified_subset(load_jsonl(args.data_dir / "test.jsonl"), args.limit, SUBSET_SEED)
    baseline = mean(record_score(record) for record in load_jsonl(args.data_dir / "train.jsonl"))
    tokenizer, model = _load(base_model, args.adapter)
    predictions = [parse_score(text) for text in _generate(tokenizer, model, records, args.batch_size)]
    labels = [record_score(record) for record in records]
    report = summarize(labels, predictions, baseline)
    report.update(
        split="test",
        subset_seed=SUBSET_SEED,
        generation_batch_size=args.batch_size,
        max_new_tokens=MAX_NEW_TOKENS,
        do_sample=False,
    )
    report["examples"] = [
        {"label_score": label, "predicted_score": score, "valid_json": ok}
        for label, (ok, score) in list(zip(labels, predictions))[:SHOW_EXAMPLES]
    ]
    report["adapter_files_mb"] = file_sizes_mb(args.adapter, "adapter_*")
    report["base_model_weights_mb"] = round(sum(file_sizes_mb(Path(base_model), "*.safetensors").values()), 1)
    base_bytes = sum(path.stat().st_size for path in Path(base_model).glob("*.safetensors"))
    adapter_bytes = (args.adapter / "adapter_model.bin").stat().st_size
    report["adapter_weights_bytes"] = adapter_bytes
    report["base_weights_bytes"] = base_bytes
    report["adapter_base_size_ratio"] = round(adapter_bytes / base_bytes, 6) if base_bytes else None
    report["adapter_reloaded"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["valid_score_rate"] > 0 else 1


if __name__ == "__main__":
    with keep_awake():
        sys.exit(main())
