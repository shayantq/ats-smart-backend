"""
تقسیم استاندارد دیتاست: Train ۸۰٪ / Validation ۱۰٪ / Test ۱۰٪.

- گروهی (Group Split): همه‌ی رکوردهای یک کارجو فقط در یک بخش قرار می‌گیرند — وگرنه مدل رزومه‌ی همان آدم را
  در آموزش دیده و نمره‌ی Test خوش‌بینانه می‌شود (Data Leakage).
- لایه‌بندی‌شده (Stratified): داخل هر سطل نمره (0-19، 20-39، ...، 80-100) جداگانه تقسیم می‌شود تا توزیع نمره
  در سه بخش یکسان بماند.
- قطعی (Deterministic): ترتیب گروه‌ها با seed ثابت بر می‌خورد؛ هر بار اجرا روی همان داده همان تقسیم را می‌دهد.

الگوریتم: در هر سطل، گروه‌ها (پس از بُر خوردن، بزرگ‌ترها اول) یکی‌یکی به بخشی داده می‌شوند که بیشترین کسری
نسبت به سهم هدفش را دارد.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Iterable

SPLITS: tuple[tuple[str, float], ...] = (("train", 0.8), ("validation", 0.1), ("test", 0.1))
DEFAULT_SEED = 42


def group_buckets(items: Iterable[tuple[str, int]]) -> tuple[dict[str, int], Counter]:
    """(گروه، سطل) هر رکورد ← سطل غالب هر گروه + تعداد رکورد هر گروه."""
    sizes: Counter = Counter()
    bucket_votes: dict[str, Counter] = defaultdict(Counter)
    for group, bucket in items:
        sizes[group] += 1
        bucket_votes[group][bucket] += 1
    # سطل غالب؛ در تساوی، سطل کوچک‌تر (قطعی، مستقل از ترتیب ورود)
    buckets = {
        group: max(votes.items(), key=lambda pair: (pair[1], -pair[0]))[0] for group, votes in bucket_votes.items()
    }
    return buckets, sizes


def _assign_bucket(groups: list[str], sizes: Counter, seed: int, bucket: int) -> dict[str, str]:
    ordered = sorted(groups)
    random.Random(f"{seed}:{bucket}").shuffle(ordered)
    ordered.sort(key=lambda group: -sizes[group])  # sort پایدار است: ترتیب بُرخورده بین هم‌اندازه‌ها حفظ می‌شود
    total = sum(sizes[group] for group in ordered)
    filled = {name: 0 for name, _ in SPLITS}
    assignment = {}
    for group in ordered:
        name = max(SPLITS, key=lambda split: split[1] * total - filled[split[0]])[0]
        assignment[group] = name
        filled[name] += sizes[group]
    return assignment


def assign_splits(items: Iterable[tuple[str, int]], seed: int = DEFAULT_SEED) -> dict[str, str]:
    """ورودی: (گروه، سطل نمره) به ازای هر رکورد. خروجی: گروه ← نام بخش."""
    buckets, sizes = group_buckets(items)
    by_bucket: dict[int, list[str]] = defaultdict(list)
    for group, bucket in buckets.items():
        by_bucket[bucket].append(group)
    assignment: dict[str, str] = {}
    for bucket in sorted(by_bucket):
        assignment.update(_assign_bucket(by_bucket[bucket], sizes, seed, bucket))
    return assignment
