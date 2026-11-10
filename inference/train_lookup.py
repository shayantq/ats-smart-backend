"""پیش‌نویس آماری از خروجی train؛ مدل اصلی باید تمام پیشنهادها را تأیید کند."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct

from tokenizers import Tokenizer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=["original", "hybrid"], default="original")
    args = parser.parse_args()
    source = Path("data/finetune/train.jsonl")
    output = Path("models/ngram") / f"train-{args.format}.bin"
    if output.exists():
        raise FileExistsError("cache قبلی حفظ می‌شود")
    tokenizer = Tokenizer.from_file("models/base-model/tokenizer.json")
    frequencies = defaultdict(Counter)
    records = tokens = 0
    for line in source.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        text = record["output"]
        if args.format == "hybrid":
            value = json.loads(text)
            compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            prefix = re.match(r'^\s*\{\s*"score"\s*:\s*\d+', text)
            compact_prefix = '{"score":' + str(value["score"])
            if prefix is None or not compact.startswith(compact_prefix):
                raise ValueError("قالب train با فرض پیشوند نمره سازگار نیست")
            text = prefix.group() + compact[len(compact_prefix) :]
            assert json.loads(text) == value
        # رکوردها مستقل‌اند؛ هیچ n-gram از مرز دو نمونه عبور نمی‌کند.
        ids = tokenizer.encode("<|im_start|>assistant\n" + text + "<|im_end|>", add_special_tokens=False).ids
        for index in range(2, len(ids)):
            frequencies[(ids[index - 2], ids[index - 1])][ids[index]] += 1
        records += 1
        tokens += len(ids)
    stats = json.loads(Path("data/finetune/stats.json").read_text(encoding="utf-8"))
    if records != stats["splits"]["train"]["records"]:
        raise ValueError("تعداد train با manifest ثبت‌شده سازگار نیست")
    output.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    with output.open("xb") as handle:
        for (first, second), counts in sorted(frequencies.items()):
            total = sum(counts.values())
            # حذف الگوهای نادر/مبهم؛ شمارش رقیب‌ها دست‌کاری نمی‌شود.
            if total < 4 or max(counts.values()) / total < 0.6:
                continue
            handle.write(struct.pack("<5i", first, second, -1, -1, len(counts)))
            for token, count in sorted(counts.items()):
                handle.write(struct.pack("<2i", token, count))
            kept += 1
    report = {
        "split": "train_only",
        "format": args.format,
        "records": records,
        "tokens": tokens,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "tokenizer_sha256": hashlib.sha256(Path("models/base-model/tokenizer.json").read_bytes()).hexdigest(),
        "source_format": "llama.cpp common/ngram-cache.cpp; 4 int32 key, int32 count, token/count int32 pairs",
        "reference_commit": "547208dca250ceb3e4c8615598d043f2b602a527",
        "static_ngram_size": 2,
        "patterns_kept": kept,
        "cache_bytes": output.stat().st_size,
        "cache_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "target_must_verify_every_proposed_token": True,
        "validation_or_test_used": False,
    }
    output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
