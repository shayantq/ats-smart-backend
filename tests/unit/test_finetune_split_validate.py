"""
تست‌های تقسیم ۸۰/۱۰/۱۰ و اعتبارسنج دیتاست (app/datasets/finetune/split.py، validate.py، validate_checks.py).

اعتبارسنج روی یک دیتاست کوچک ساختگی اجرا می‌شود که با همان ساز و کار build نوشته شده؛ سپس هر بار یک نوع
«مسمومیت» (ایمیل، تلفن، نام، U+FFFD، رکورد بیش از حد بلند، کارجوی مشترک بین دو بخش، ...) تزریق و رد شدنش بررسی می‌شود.
"""

import json
import random
from collections import Counter
from pathlib import Path

import pytest

from app.core.crypto import blind_index_token
from app.datasets.finetune.cleanse import CleansingConfig, Cleanser
from app.datasets.finetune.split import SPLITS, assign_splits
from app.datasets.finetune.tokenization import load_tokenizer
from app.datasets.finetune.validate import main as validate_main
from app.datasets.finetune.validate import validate_dataset
from tests.finetune_helpers import SAMPLE_RESUME, build_test_tokenizer, sample_source

TOLERANCE = 0.15  # دیتاست تست کوچک است؛ تلورانس ±۱٪ روی دیتاست ۱۰ هزارتایی بررسی می‌شود


# ---------------------------------------------------------------------------
# تقسیم
# ---------------------------------------------------------------------------
def _items(count: int, seed: int = 1) -> list[tuple[str, int]]:
    rng = random.Random(seed)
    return [(f"g{rng.randint(0, count // 2)}", rng.randint(0, 4)) for _ in range(count)]


def test_split_is_deterministic():
    items = _items(3000)
    assert assign_splits(items, seed=42) == assign_splits(list(items), seed=42)
    assert assign_splits(items, seed=42) != assign_splits(items, seed=7)


def test_split_ratios_are_within_one_percent_and_groups_never_cross():
    items = _items(10_000)
    assignment = assign_splits(items)
    counts = Counter(assignment[group] for group, _ in items)
    for name, target in SPLITS:
        assert abs(counts[name] / len(items) - target) <= 0.01
    assert len(assignment) == len({group for group, _ in items})  # هر گروه دقیقاً یک بخش


def test_split_is_stratified_by_score_bucket():
    items = [(f"g{index}", index % 5) for index in range(5000)]
    assignment = assign_splits(items)
    for bucket in range(5):
        in_bucket = [assignment[group] for group, item_bucket in items if item_bucket == bucket]
        assert abs(in_bucket.count("train") / len(in_bucket) - 0.8) <= 0.01


# ---------------------------------------------------------------------------
# ساخت دیتاست کوچک تست
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def tokenizer_path(tmp_path_factory) -> str:
    return build_test_tokenizer(tmp_path_factory.mktemp("tok"))


def _variant(index: int) -> str:
    words = ["Redis", "Kafka", "GraphQL", "Nginx", "Ansible", "Pandas", "Figma", "Terraform", "Vue", "Swift"]
    picked = " ".join(words[(index + offset) % len(words)] * (1 + (index + offset) % 3) for offset in range(4))
    return SAMPLE_RESUME + f"\nپروژه‌ها\n{picked} نسخه‌ی {'الف' * (index + 1)}"


def write_dataset(directory: Path, tokenizer_path: str, count: int = 40) -> None:
    cleanser = Cleanser(load_tokenizer(tokenizer_path), CleansingConfig(max_tokens=100_000))
    cleans = [cleanser.process(sample_source(candidate_key=f"g{i}", resume_text=_variant(i))) for i in range(count)]
    assert all(cleans)
    assignment = assign_splits([(clean.group, clean.bucket) for clean in cleans])
    manifest = {name: [] for name, _ in SPLITS}
    lines = {name: [] for name, _ in SPLITS}
    for clean in cleans:
        name = assignment[clean.group]
        lines[name].append(json.dumps(clean.record, ensure_ascii=False))
        manifest[name].append({"group": clean.group, "pii": clean.pii_hashes})
    for name, rows in lines.items():
        (directory / f"{name}.jsonl").write_text("".join(row + "\n" for row in rows), encoding="utf-8")
    (directory / "manifest.json").write_text(json.dumps({"splits": manifest}), encoding="utf-8")


@pytest.fixture
def dataset(tmp_path, tokenizer_path) -> Path:
    write_dataset(tmp_path, tokenizer_path)
    return tmp_path


def _validate(directory: Path, tokenizer_path: str, max_tokens: int = 100_000) -> dict:
    return validate_dataset(directory, load_tokenizer(tokenizer_path), max_tokens, TOLERANCE)


def _poison(directory: Path, mutate, split: str = "train", line: int = 0) -> None:
    path = directory / f"{split}.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(rows[line])
    rows[line] = mutate(record)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _with_input(text: str):
    def mutate(record):
        record["input"] += text
        return json.dumps(record, ensure_ascii=False)

    return mutate


def test_clean_dataset_passes(dataset, tokenizer_path):
    result = _validate(dataset, tokenizer_path)
    assert result["status"] == "pass", result["issues"]
    assert sum(result["records"].values()) == 40


@pytest.mark.parametrize(
    ("injected", "code"),
    [
        (" sara.k@example.net", "pii_email"),
        (" 0912 765 4321", "pii_phone"),
        (" +98 21 4455 6677", "pii_phone"),
        (" https://cv.example.net/me", "pii_url"),
        (" @someone_handle", "pii_handle"),
        (" 0023456789", "pii_national_id"),
        (" Sepideh", "pii_identity"),
        (" behance.net/someone", "pii_url"),
        (" someone-portfolio.ir", "pii_url"),
        (" 0912/765/4321", "pii_phone"),
        (" سال تولد: 1371", "pii_birth_date"),
        (" آدرس: خیابان ساختگی پلاک 3", "pii_address"),
        (" کوهستانی", "pii_identity"),
        (" خراب�", "broken_replacement_char"),
        (" \x07", "broken_control_char"),
        (" ​", "broken_invisible_char"),
        (" " + "مهندس".encode("utf-8").decode("latin-1"), "broken_mojibake"),
    ],
)
def test_injected_problem_fails_validation(dataset, tokenizer_path, injected, code):
    _poison(dataset, _with_input(injected))
    result = _validate(dataset, tokenizer_path)
    assert result["status"] == "fail"
    assert code in result["issues"]
    assert {"file": "train.jsonl", "line": 1, "code": code} in result["examples"]


def test_report_never_contains_record_content(dataset, tokenizer_path):
    _poison(dataset, _with_input(" sara.k@example.net"))
    assert "example.net" not in json.dumps(_validate(dataset, tokenizer_path), ensure_ascii=False)


def test_oversize_record_is_context_overflow(dataset, tokenizer_path):
    result = _validate(dataset, tokenizer_path, max_tokens=200)
    assert result["status"] == "fail"
    assert result["issues"]["context_overflow"] == 40
    assert result["tokens"]["train"]["max"] > 200


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (lambda record: "{not json", "schema_invalid_json"),
        (lambda record: json.dumps({"instruction": "x", "input": "y"}), "schema_keys"),
        (lambda record: json.dumps({**record, "extra": "z"}), "schema_keys"),
        (lambda record: json.dumps({**record, "input": "  "}), "schema_empty_field"),
        (lambda record: json.dumps({**record, "output": "نه JSON"}), "schema_output_json"),
        (lambda record: json.dumps({**record, "output": json.dumps({"score": 130})}), "schema_score_range"),
        (lambda record: json.dumps({**record, "input": "\ud800 تنها"}), "broken_surrogate"),
    ],
)
def test_schema_problems_fail_validation(dataset, tokenizer_path, raw, code):
    _poison(dataset, raw)
    assert code in _validate(dataset, tokenizer_path)["issues"]


def test_invalid_utf8_fails_validation(dataset, tokenizer_path):
    path = dataset / "train.jsonl"
    path.write_bytes(path.read_bytes() + b'{"instruction": "\xff\xfe"}\n')
    issues = _validate(dataset, tokenizer_path)["issues"]
    assert "schema_invalid_utf8" in issues
    assert "manifest_mismatch" in issues


def test_candidate_shared_between_splits_is_leakage(dataset, tokenizer_path):
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["splits"]["test"][0]["group"] = manifest["splits"]["train"][0]["group"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert "leakage_group" in _validate(dataset, tokenizer_path)["issues"]


def test_ratio_outside_tolerance_fails(dataset, tokenizer_path):
    (dataset / "train.jsonl").write_text("", encoding="utf-8")
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["splits"]["train"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert "split_ratio" in _validate(dataset, tokenizer_path)["issues"]


def test_missing_manifest_or_split_file_fails(dataset, tokenizer_path):
    (dataset / "manifest.json").unlink()
    (dataset / "test.jsonl").unlink()
    issues = _validate(dataset, tokenizer_path)["issues"]
    assert "manifest_missing" in issues and "missing_file" in issues


def test_poisoned_sample_reports_every_problem_and_cli_exits_nonzero(dataset, tokenizer_path, capsys):
    """نمونه‌ی مسموم معیار پذیرش: ایمیل، تلفن، نام، U+FFFD، رکورد بلند و کارجوی مشترک بین بخش‌ها با هم."""
    _poison(dataset, _with_input(" sara.k@example.net 0912 765 4321 Sepideh خراب�"), line=0)
    _poison(dataset, _with_input(" پروژه" * 3000), line=1)
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["splits"]["test"][0]["group"] = manifest["splits"]["train"][2]["group"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    exit_code = validate_main(
        [str(dataset), "--tokenizer", tokenizer_path, "--max-tokens", "6000", "--ratio-tolerance", str(TOLERANCE)]
    )
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    for code in (
        "pii_email",
        "pii_phone",
        "pii_identity",
        "broken_replacement_char",
        "context_overflow",
        "leakage_group",
    ):
        assert code in report["issues"], code


def test_cli_exits_zero_on_clean_dataset(dataset, tokenizer_path, capsys):
    assert validate_main([str(dataset), "--tokenizer", tokenizer_path, "--ratio-tolerance", str(TOLERANCE)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def test_manifest_hashes_match_validator_tokenization():
    assert blind_index_token("sepideh") == blind_index_token("Sepideh".lower())
