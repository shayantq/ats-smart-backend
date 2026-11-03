"""
ساخت دیتاست آموزش تکمیلی از دیتابیس:

    python -m app.datasets.finetune.build --out data/finetune --tokenizer data/tokenizer/tokenizer.json

مراحل: شمارش جفت‌های واجد شرایط (گیت --min-pairs) ← خواندن جریانی ← پاک‌سازی و ناشناس‌سازی هر جفت (cleanse.py)
← نوشتن موقت روی دیسک (فقط رکوردهای ناشناس‌شده) ← تقسیم گروهی ۸۰/۱۰/۱۰ ← train/validation/test.jsonl +
manifest.json (هش‌های HMAC برای اعتبارسنجی؛ بدون متن ساده) + stats.json (فقط شمارش‌ها).

همه‌ی فایل‌ها با دسترسی 600 و پوشه با 700 ساخته می‌شوند. خروجی کنسول فقط عدد است، هرگز محتوای رکورد.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.crypto import validate_keys
from app.datasets.finetune.cleanse import RULES, CleansingConfig, Cleanser
from app.datasets.finetune.extract import DEFAULT_BATCH_SIZE, count_eligible_pairs, iter_pair_sources, readonly_session
from app.datasets.finetune.records import INSTRUCTION_VERSION
from app.datasets.finetune.split import DEFAULT_SEED, SPLITS, assign_splits
from app.datasets.finetune.tokenization import DEFAULT_MAX_TOKENS, load_tokenizer, tokenizer_fingerprint

DEFAULT_MIN_PAIRS = 10_000
MANIFEST_FORMAT = "ats-finetune-manifest-v1"
TEMP_NAME = ".records.tmp.jsonl"
EXIT_INSUFFICIENT_PAIRS = 2
EXIT_FAILURE = 1


class InsufficientPairsError(Exception):
    def __init__(self, eligible: int, required: int) -> None:
        super().__init__(f"تعداد جفت‌های واجد شرایط کافی نیست: {eligible} از حداقل {required}")
        self.eligible = eligible
        self.required = required


@dataclass(frozen=True)
class BuildOptions:
    out_dir: Path
    tokenizer_path: str
    min_pairs: int = DEFAULT_MIN_PAIRS
    seed: int = DEFAULT_SEED
    batch_size: int = DEFAULT_BATCH_SIZE
    cleansing: CleansingConfig = field(default_factory=CleansingConfig)


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def open_private(path: Path, mode: str = "w"):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(path, 0o600)
    return os.fdopen(descriptor, mode, encoding="utf-8", newline="\n")


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


async def _collect(db, options: BuildOptions, cleanser: Cleanser, temp_path: Path) -> tuple[int, list]:
    fetched, meta = 0, []
    with open_private(temp_path) as handle:
        async for source in iter_pair_sources(db, options.batch_size):
            fetched += 1
            clean = cleanser.process_safely(source)
            if clean is None:
                continue
            handle.write(_dump({"g": clean.group, "p": clean.pii_hashes, "t": clean.tokens, "r": clean.record}) + "\n")
            meta.append((clean.group, clean.bucket))
    return fetched, meta


def _write_splits(temp_path: Path, out_dir: Path, assignment: dict[str, str]) -> tuple[dict, dict]:
    names = [name for name, _ in SPLITS]
    handles = {name: open_private(out_dir / f"{name}.jsonl") for name in names}
    manifest: dict[str, list] = {name: [] for name in names}
    tokens: dict[str, list[int]] = {name: [] for name in names}
    try:
        with temp_path.open(encoding="utf-8") as source:
            for line in source:
                item = json.loads(line)
                name = assignment[item["g"]]
                handles[name].write(_dump(item["r"]) + "\n")
                manifest[name].append({"group": item["g"], "pii": item["p"]})
                tokens[name].append(item["t"])
    finally:
        for handle in handles.values():
            handle.close()
    return manifest, tokens


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


def _split_stats(manifest: dict, tokens: dict) -> dict:
    total = sum(len(rows) for rows in manifest.values()) or 1
    return {
        name: {
            "records": len(rows),
            "ratio": round(len(rows) / total, 4),
            "groups": len({row["group"] for row in rows}),
            "tokens": {key: _percentile(tokens[name], frac) for key, frac in (("p50", 0.5), ("p95", 0.95), ("max", 1))},
        }
        for name, rows in manifest.items()
    }


def _stats(options: BuildOptions, eligible: int, fetched: int, cleanser: Cleanser, manifest: dict, tokens: dict):
    return {
        "instruction_version": INSTRUCTION_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": options.seed,
        "tokenizer_sha256": tokenizer_fingerprint(options.tokenizer_path),
        "min_pairs": options.min_pairs,
        "eligible_pairs": eligible,
        "fetched_pairs": fetched,
        "kept": cleanser.counters["kept"],
        "dropped": {rule: cleanser.counters[rule] for rule in RULES},
        "cleansing": asdict(options.cleansing),
        "splits": _split_stats(manifest, tokens),
    }


async def build_dataset(db, options: BuildOptions) -> dict:
    eligible = await count_eligible_pairs(db)
    if eligible < options.min_pairs:
        raise InsufficientPairsError(eligible, options.min_pairs)
    cleanser = Cleanser(load_tokenizer(options.tokenizer_path), options.cleansing)
    ensure_private_dir(options.out_dir)
    temp_path = options.out_dir / TEMP_NAME
    try:
        fetched, meta = await _collect(db, options, cleanser, temp_path)
        manifest, tokens = _write_splits(temp_path, options.out_dir, assign_splits(meta, options.seed))
    finally:
        temp_path.unlink(missing_ok=True)
    stats = _stats(options, eligible, fetched, cleanser, manifest, tokens)
    with open_private(options.out_dir / "manifest.json") as handle:
        json.dump({"format": MANIFEST_FORMAT, "splits": manifest}, handle)
    with open_private(options.out_dir / "stats.json") as handle:
        json.dump(stats, handle, ensure_ascii=False, indent=2)
    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.datasets.finetune.build", description=__doc__.split("\n")[1])
    parser.add_argument("--out", type=Path, default=Path("data/finetune"))
    parser.add_argument("--tokenizer", required=True, help="مسیر tokenizer.json مدل پایه‌ی هدف")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--min-pairs", type=int, default=DEFAULT_MIN_PAIRS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--min-resume-chars", type=int, default=CleansingConfig.min_resume_chars)
    parser.add_argument("--max-resume-chars", type=int, default=CleansingConfig.max_resume_chars)
    parser.add_argument("--max-experience-years", type=float, default=CleansingConfig.max_experience_years)
    return parser.parse_args(argv)


def options_from_args(args: argparse.Namespace) -> BuildOptions:
    cleansing = CleansingConfig(
        min_resume_chars=args.min_resume_chars,
        max_resume_chars=args.max_resume_chars,
        max_experience_years=args.max_experience_years,
        max_tokens=args.max_tokens,
    )
    return BuildOptions(args.out, args.tokenizer, args.min_pairs, args.seed, args.batch_size, cleansing)


async def _run(options: BuildOptions) -> dict:
    async with readonly_session() as db:
        return await build_dataset(db, options)


def main(argv: list[str] | None = None) -> int:
    options = options_from_args(parse_args(argv))
    validate_keys()
    try:
        stats = asyncio.run(_run(options))
    except InsufficientPairsError as error:
        print(
            json.dumps({"status": "insufficient_pairs", "eligible_pairs": error.eligible, "min_pairs": error.required})
        )
        print(str(error), file=sys.stderr)
        return EXIT_INSUFFICIENT_PAIRS
    except Exception as error:  # noqa: BLE001 — فقط نوع خطا چاپ می‌شود؛ پیام ممکن است داده‌ی رکورد داشته باشد
        print(json.dumps({"status": "error", "error_type": type(error).__name__}))
        return EXIT_FAILURE
    summary = {key: stats[key] for key in ("eligible_pairs", "fetched_pairs", "kept", "dropped")}
    summary["splits"] = {name: split["records"] for name, split in stats["splits"].items()}
    print(json.dumps({"status": "ok", **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
