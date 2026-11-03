"""
اعتبارسنج دیتاست آموزش تکمیلی:

    python -m app.datasets.finetune.validate data/finetune --tokenizer data/tokenizer/tokenizer.json

بررسی می‌کند: ساختار (UTF-8، JSON معتبر، دقیقاً سه کلید، output با score صحیح 0-100)، نبود اطلاعات هویتی
(الگوها + هش شناسه‌های هر رکورد در manifest.json)، نبود توکن/نویسه‌ی خراب (U+FFFD، کنترلی، surrogate، نامرئی،
mojibake، رفت‌وبرگشت توکنایزر)، سرریز کانتکست (طول کل گفت‌وگو ≤ --max-tokens)، نشتی کارجو بین بخش‌ها و نسبت
۸۰/۱۰/۱۰ با تلورانس. با هر خطا کد خروج 1 می‌دهد. گزارش فقط کد خطا و شماره‌ی خط دارد، نه محتوا.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from tokenizers import Tokenizer

from app.datasets.finetune.validate_checks import (
    check_broken,
    check_pii,
    check_schema,
    check_splits,
    conversation_tokens,
)

TARGETS = {"train": 0.8, "validation": 0.1, "test": 0.1}
DEFAULT_TOLERANCE = 0.01
DEFAULT_MAX_TOKENS = 4096
MAX_EXAMPLES = 25


@dataclass
class Report:
    issues: Counter = field(default_factory=Counter)
    examples: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)

    def add(self, split: str, line: int, code: str) -> None:
        self.issues[code] += 1
        if len(self.examples) < MAX_EXAMPLES:
            self.examples.append({"file": f"{split}.jsonl", "line": line, "code": code})

    def as_dict(self) -> dict:
        return {
            "status": "fail" if self.issues else "pass",
            "records": self.counts,
            "tokens": self.tokens,
            "issues": dict(sorted(self.issues.items())),
            "examples": self.examples,
        }


def _load_manifest(directory: Path, report: Report) -> dict:
    try:
        return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["splits"]
    except (OSError, ValueError, KeyError):
        report.add("manifest", 0, "manifest_missing")
        return {}


def _check_record(raw: bytes, entry: dict | None, tokenizer: Tokenizer, max_tokens: int) -> tuple[list[str], int]:
    record, issues = check_schema(raw)
    if record is None:
        return issues, 0
    issues += check_pii(record, set((entry or {}).get("pii") or ()))
    issues += check_broken(record, tokenizer)
    if "broken_surrogate" in issues:
        return issues, 0
    tokens = conversation_tokens(record, tokenizer)
    if tokens > max_tokens:
        issues.append("context_overflow")
    return issues, tokens


def _validate_split(directory: Path, name: str, entries: list, tokenizer: Tokenizer, max_tokens: int, report: Report):
    path = directory / f"{name}.jsonl"
    if not path.exists():
        report.add(name, 0, "missing_file")
        return set()
    lengths, line_count = [], 0
    with path.open("rb") as handle:
        for line_count, raw in enumerate(handle, start=1):
            entry = entries[line_count - 1] if line_count <= len(entries) else None
            if entry is None:
                report.add(name, line_count, "manifest_mismatch")
            issues, tokens = _check_record(raw.rstrip(b"\n"), entry, tokenizer, max_tokens)
            for code in issues:
                report.add(name, line_count, code)
            lengths.append(tokens)
    if line_count < len(entries):
        report.add(name, line_count, "manifest_mismatch")
    report.counts[name] = line_count
    ordered = sorted(lengths) or [0]
    report.tokens[name] = {"p95": ordered[int(0.95 * (len(ordered) - 1))], "max": ordered[-1]}
    return {entry["group"] for entry in entries}


def validate_dataset(directory: Path, tokenizer: Tokenizer, max_tokens: int, tolerance: float) -> dict:
    report = Report()
    manifest = _load_manifest(directory, report)
    groups = {
        name: _validate_split(directory, name, manifest.get(name, []), tokenizer, max_tokens, report)
        for name in TARGETS
    }
    for issue in check_splits(groups, report.counts, TARGETS, tolerance):
        report.add(issue.split(":", 1)[1].split("/", 1)[0], 0, issue.split(":", 1)[0])
    return report.as_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.datasets.finetune.validate", description=__doc__.split("\n")[1]
    )
    parser.add_argument("directory", type=Path)
    parser.add_argument("--tokenizer", required=True, help="همان tokenizer.json که دیتاست با آن ساخته شده")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--ratio-tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args(argv)
    result = validate_dataset(
        args.directory, Tokenizer.from_file(args.tokenizer), args.max_tokens, args.ratio_tolerance
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
