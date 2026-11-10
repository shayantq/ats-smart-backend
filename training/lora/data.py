"""
آماده‌سازی داده‌ی آموزش LoRA از خروجی app/datasets/finetune (train/validation/test.jsonl).

- هر رکورد با قالب چت خود توکنایزر مدل پایه رندر می‌شود: system=instruction، user=input، assistant=output.
- loss فقط روی توکن‌های پاسخ (assistant) حساب می‌شود: برچسب بخش system/user و padding برابر ‎-100 است؛
  مدل یاد می‌گیرد «ارزیابی» تولید کند، نه اینکه متن رزومه را حفظ کند.
- رکورد بلندتر از max_seq_len هرگز بی‌صدا بریده نمی‌شود: کنار گذاشته و شمرده می‌شود.
- زیرمجموعه‌ی ثابت validation برای eval های میانی: لایه‌بندی‌شده بر اساس سطل نمره، با seed ثابت.
"""

from __future__ import annotations

import json
import hashlib
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

IGNORE_INDEX = -100
SCORE_BUCKET_WIDTH = 20
SCORE_BUCKETS = 5
SPLIT_NAMES = ("train", "validation", "test")


def dataset_fingerprint(data_dir: Path) -> dict[str, str]:
    """اثر انگشت ورودی اجرا؛ ادامه‌ی آموزش با دیتاست عوض‌شده مجاز نیست."""
    paths = [data_dir / f"{name}.jsonl" for name in SPLIT_NAMES]
    paths += [data_dir / "manifest.json", data_dir / "stats.json"]
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def audited_records(data_dir: Path) -> tuple[dict[str, list[dict]], dict]:
    """پیش از آموزش: ساختار، شمارش و نبود هم‌پوشانی کارجو یا ورودی بین سه بخش."""
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))["splits"]
    stats = json.loads((data_dir / "stats.json").read_text(encoding="utf-8"))
    splits, groups, inputs = {}, {}, {}
    for name in SPLIT_NAMES:
        records = load_jsonl(data_dir / f"{name}.jsonl")
        if not records or len(records) != len(manifest[name]) or len(records) != stats["splits"][name]["records"]:
            raise ValueError(f"شمارش داده یا manifest بخش {name} ناسازگار یا خالی است")
        for index, record in enumerate(records):
            try:
                if set(record) != {"instruction", "input", "output"}:
                    raise ValueError
                if not all(isinstance(value, str) and value.strip() for value in record.values()):
                    raise ValueError
                score = json.loads(record["output"])["score"]
                if type(score) is not int or not 0 <= score <= 100:
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise ValueError(f"ساختار رکورد {index + 1} در بخش {name} نامعتبر است") from None
        groups[name] = {entry["group"] for entry in manifest[name]}
        if any(not isinstance(group, str) or not group for group in groups[name]):
            raise ValueError(f"شناسه‌ی گروه در بخش {name} نامعتبر است")
        inputs[name] = {
            hashlib.sha256(json.dumps([r["instruction"], r["input"]], ensure_ascii=False).encode()).hexdigest()
            for r in records
        }
        for previous in splits:
            if groups[name] & groups[previous] or inputs[name] & inputs[previous]:
                raise ValueError(f"نشت داده بین بخش‌های {previous} و {name}")
        splits[name] = records
    report = {"records": {name: len(rows) for name, rows in splits.items()}, "split_isolation_passed": True}
    return splits, report


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def chat_messages(record: dict) -> list[dict]:
    return [
        {"role": "system", "content": record["instruction"]},
        {"role": "user", "content": record["input"]},
        {"role": "assistant", "content": record["output"]},
    ]


def _token_ids(encoded) -> list[int]:
    """apply_chat_template بسته به نسخه فهرست شناسه یا BatchEncoding برمی‌گرداند."""
    if hasattr(encoded, "keys"):
        encoded = encoded["input_ids"]
    return list(encoded)


def prompt_ids(tokenizer, record: dict) -> list[int]:
    """ورودی تولید (system + user + شروع پاسخ assistant) — برای ارزیابی پس از آموزش."""
    messages = chat_messages(record)[:2]
    return _token_ids(tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True))


def encode_record(tokenizer, record: dict, max_seq_len: int) -> dict | None:
    prompt = prompt_ids(tokenizer, record)
    full = _token_ids(tokenizer.apply_chat_template(chat_messages(record), tokenize=True))
    if full[: len(prompt)] != prompt:
        raise ValueError("قالب چت توکنایزر پیشوند ثابتی برای بخش پاسخ نمی‌سازد؛ ماسک loss قابل اعتماد نیست")
    if len(full) > max_seq_len:
        return None
    return {"input_ids": full, "labels": [IGNORE_INDEX] * len(prompt) + full[len(prompt) :]}


@dataclass(frozen=True)
class EncodedSplit:
    examples: list[dict]
    dropped_too_long: int


def encode_split(tokenizer, records: list[dict], max_seq_len: int) -> EncodedSplit:
    encoded = [encode_record(tokenizer, record, max_seq_len) for record in records]
    kept = [example for example in encoded if example is not None]
    return EncodedSplit(kept, len(encoded) - len(kept))


def record_score(record: dict) -> int:
    return int(json.loads(record["output"])["score"])


def _bucket(record: dict) -> int:
    return min(record_score(record) // SCORE_BUCKET_WIDTH, SCORE_BUCKETS - 1)


def stratified_subset(records: list[dict], size: int, seed: int) -> list[dict]:
    """زیرمجموعه‌ی ثابت (قطعی) با همان توزیع سطل نمره‌ی کل؛ ترتیب اصلی رکوردها حفظ می‌شود."""
    if size >= len(records):
        return list(records)
    by_bucket: dict[int, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        by_bucket[_bucket(record)].append(index)
    quotas = {bucket: size * len(indices) / len(records) for bucket, indices in by_bucket.items()}
    counts = {bucket: int(quota) for bucket, quota in quotas.items()}
    by_remainder = sorted(quotas, key=lambda bucket: (counts[bucket] - quotas[bucket], bucket))
    for bucket in by_remainder[: size - sum(counts.values())]:
        counts[bucket] += 1
    rng = random.Random(seed)
    chosen = [index for bucket in sorted(by_bucket) for index in rng.sample(by_bucket[bucket], counts[bucket])]
    return [records[index] for index in sorted(chosen)]


class ListDataset:
    """Dataset ساده‌ی در حافظه برای Trainer (۸ هزار نمونه‌ی توکن‌شده چند ده مگابایت است)."""

    def __init__(self, examples: list[dict]) -> None:
        self.examples = examples

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> dict:
        return self.examples[index]


class PadCollator:
    """هم‌طول‌سازی دسته: input_ids با pad، labels با ‎-100، attention_mask صفر برای padding."""

    def __init__(self, pad_token_id: int, answer_logits_only: bool = False) -> None:
        self.pad_token_id = pad_token_id
        self.answer_logits_only = answer_logits_only

    def __call__(self, features: list[dict]):
        import torch

        length = max(len(feature["input_ids"]) for feature in features)
        batch = {"input_ids": [], "labels": [], "attention_mask": []}
        for feature in features:
            padding = length - len(feature["input_ids"])
            batch["input_ids"].append(feature["input_ids"] + [self.pad_token_id] * padding)
            batch["labels"].append(feature["labels"] + [IGNORE_INDEX] * padding)
            batch["attention_mask"].append([1] * len(feature["input_ids"]) + [0] * padding)
        batch = {key: torch.tensor(value, dtype=torch.long) for key, value in batch.items()}
        if self.answer_logits_only:
            # متن کامل وارد Transformer می‌شود؛ فقط خروجی پرهزینه‌ی واژگان روی موقعیت‌های دارای loss ساخته می‌شود.
            # shift_labels همان هم‌ترازی علّی داخلی کتابخانه است، پیش از انتخاب موقعیت‌ها.
            shifted = batch["labels"][:, 1:]
            positions = (shifted != IGNORE_INDEX).any(dim=0).nonzero(as_tuple=True)[0]
            if positions.numel() == 0:
                raise ValueError("دسته هیچ توکن پاسخ قابل آموزش ندارد")
            batch["logits_to_keep"] = positions
            batch["shift_labels"] = shifted[:, positions].contiguous()
        return batch
