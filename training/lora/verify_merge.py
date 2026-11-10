"""مقایسهٔ رفتاری روی validation ثابت؛ آستانه‌ها پیش از دیدن نتیجه ثابت‌اند."""

import argparse
import gc
import json
from pathlib import Path

from training.lora.data import load_jsonl, prompt_ids, stratified_subset
from training.lora.merge import sha256

TOLERANCES = {"max_logit_absolute": 0.5, "logit_rmse": 0.05, "top1_agreement_min": 0.95}


def main():
    import torch
    from accelerate import cpu_offload
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from training.lora.resources import GIB, windows_memory

    memory = windows_memory()
    if memory and memory["commit_available"] < 9 * GIB:
        raise RuntimeError("بررسی BF16 روی CPU به حداقل ۹ GiB حافظهٔ commit آزاد نیاز دارد")
    torch.set_num_threads(4)

    parser = argparse.ArgumentParser()
    parser.add_argument("--merged", type=Path, default=Path("models/ats-merged-bf16"))
    parser.add_argument("--base", type=Path, default=Path("models/base-model"))
    parser.add_argument("--dtype", choices=["bfloat16", "float32"], default="bfloat16")
    parser.add_argument("--report", type=Path, default=Path("training/reports/inference/merge_verification.json"))
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError("گزارش قبلی بازنویسی نمی‌شود")
    tokenizer = AutoTokenizer.from_pretrained("models/base-model", local_files_only=True)
    records = stratified_subset(load_jsonl(Path("data/finetune/validation.jsonl")), 3, 2026)
    sequences = []
    for record in records:
        prefix = prompt_ids(tokenizer, record)
        answer = tokenizer.encode(record["output"], add_special_tokens=False)[:32]
        sequences.append((prefix + answer, len(prefix) - 1))
    results = []
    manifest = json.loads(Path("models/base-model/download_manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["sha256"].items():
        if sha256(Path("models/base-model") / name) != digest:
            raise ValueError("وزن پایه تغییر کرده است؛ مقایسه متوقف شد")
    for mode in ("adapter", "merged"):
        model = AutoModelForCausalLM.from_pretrained(
            args.base if mode == "adapter" else args.merged,
            local_files_only=True,
            dtype=getattr(torch, args.dtype),
            device_map={"": "cpu"},
            attn_implementation="sdpa",
        )
        if mode == "adapter":
            model = PeftModel.from_pretrained(
                model, "training/outputs/ats-20261108-fast-01/adapter", is_trainable=False
            )
        if any(parameter.is_meta for parameter in model.parameters()):
            raise RuntimeError("وزن meta در مقایسه مجاز نیست")
        # آداپتر پیش از نصب hook بارگذاری شده؛ staging فقط در RAM است و فایلی بازنویسی نمی‌شود.
        cpu_offload(model, execution_device=torch.device("cuda:0"))
        model.eval()
        logits = []
        for ids, start in sequences:
            with torch.inference_mode():
                batch = torch.tensor([ids], device="cuda:0")
                # فقط ۳۳ موقعیت آخر؛ ساخت logits کل دنباله حافظهٔ اضافی مصرف می‌کند.
                value = model(batch, use_cache=False, logits_to_keep=len(ids) - start).logits.float().cpu()
                logits.append(value)
                print(json.dumps({"mode": mode, "verified_inputs": len(logits)}), flush=True)
        results.append(logits)
        del model, batch, value
        gc.collect()
        torch.cuda.empty_cache()
    measurements = []
    for before, after in zip(*results):
        delta = before - after
        measurements.append(
            {
                "max_logit_absolute": delta.abs().max().item(),
                "logit_rmse": delta.square().mean().sqrt().item(),
                "top1_agreement": (before.argmax(-1) == after.argmax(-1)).float().mean().item(),
            }
        )
    passed = all(
        row["max_logit_absolute"] <= TOLERANCES["max_logit_absolute"]
        and row["logit_rmse"] <= TOLERANCES["logit_rmse"]
        and row["top1_agreement"] >= TOLERANCES["top1_agreement_min"]
        for row in measurements
    )
    report = {
        "passed": passed,
        "tolerances_declared_before_run": TOLERANCES,
        "data": "synthetic_validation",
        "records": 3,
        "seed": 2026,
        "teacher_forced_answer_tokens": 32,
        "dtype": args.dtype + "_nonquantized",
        "execution": "GPU with RAM-only cpu_offload after adapter load; no disk offload",
        "measurements": measurements,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, digest in manifest["sha256"].items():
        if sha256(Path("models/base-model") / name) != digest:
            raise RuntimeError("اثر انگشت پایه پس از مقایسه تغییر کرده است")
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
