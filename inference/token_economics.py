"""آمار طول validation و قالب JSON؛ بدون ثبت متن یا استفاده از test برای تنظیم موتور."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from tokenizers import Tokenizer


def statistics(values):
    ordered = sorted(values)
    return {f"p{p}": ordered[max(0, math.ceil(p * len(ordered) / 100) - 1)] for p in (50, 95, 99)} | {
        "max": ordered[-1]
    }


def scaffold_mask(text):
    # این‌ها فقط نامزدهای ساختاری‌اند؛ یکتابودن توکن مجاز از روی این ماسک اثبات نمی‌شود.
    mask = [False] * len(text)
    index = 0
    while index < len(text):
        if text[index] == '"':
            _, end = json.decoder.scanstring(text, index + 1)
            following = end
            while following < len(text) and text[following].isspace():
                following += 1
            if following < len(text) and text[following] == ":":
                mask[index:end] = [True] * (end - index)
            else:
                mask[index] = mask[end - 1] = True
            index = end
        else:
            mask[index] = text[index].isspace() or text[index] in "{}[],:"
            index += 1
    return mask


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/finetune/validation.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("training/reports/inference/token_economics.json"))
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError("گزارش قبلی حفظ می‌شود")
    tokenizer = Tokenizer.from_file("models/base-model/tokenizer.json")
    counts = {name: [] for name in ("original", "compact", "hybrid", "scaffold_candidates", "other_tokens", "prompt")}
    for line in args.data.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        text = record["output"]
        value = json.loads(text)
        compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        prefix = re.match(r'^\s*\{\s*"score"\s*:\s*\d+', text)
        compact_prefix = '{"score":' + str(value["score"])
        if prefix is None or not compact.startswith(compact_prefix):
            raise ValueError("ترتیب پیشوند نمره با فرض آزمایش یکسان نیست")
        hybrid = prefix.group() + compact[len(compact_prefix) :]
        assert json.loads(hybrid) == value
        encoded = tokenizer.encode(text, add_special_tokens=False)
        mask = scaffold_mask(text)
        candidates = sum(end > start and all(mask[start:end]) for start, end in encoded.offsets)
        counts["original"].append(len(encoded.ids))
        counts["compact"].append(len(tokenizer.encode(compact, add_special_tokens=False).ids))
        counts["hybrid"].append(len(tokenizer.encode(hybrid, add_special_tokens=False).ids))
        counts["scaffold_candidates"].append(candidates)
        counts["other_tokens"].append(len(encoded.ids) - candidates)
        prompt = (
            "<|im_start|>system\n"
            + record["instruction"]
            + "<|im_end|>\n<|im_start|>user\n"
            + record["input"]
            + "<|im_end|>\n<|im_start|>assistant\n"
        )
        counts["prompt"].append(len(tokenizer.encode(prompt, add_special_tokens=False).ids))
    report = {
        "split": args.data.name,
        "source_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
        "records": len(counts["original"]),
        "synthetic": True,
        "gold_lengths_not_generated_outputs": True,
        "counts_exclude_eos": True,
        "scaffold_candidates_are_not_proven_forced_tokens": True,
        "token_counts": {name: statistics(values) for name, values in counts.items()},
        "decode_rate_needed_with_2_73_seconds_budget": {
            name: {key: round((value + 1) / 2.73, 2) for key, value in statistics(counts[name]).items()}
            for name in ("original", "compact", "hybrid")
        },
        "prompt_plus_reserved_640_exceeds_2048": sum(value + 640 > 2048 for value in counts["prompt"]),
        "original_gold_exceeds_640": sum(value + 1 > 640 for value in counts["original"]),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
