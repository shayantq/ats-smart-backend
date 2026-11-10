"""تست‌های بخش پایتون خالص ارزیابی آداپتر (training/lora/evaluate.py): تجزیه‌ی نمره، خلاصه‌ی MAE، اندازه‌ی فایل‌ها."""

import pytest

from training.lora.evaluate import file_sizes_mb, parse_score, summarize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"score": 78, "verdict": "مناسب"}', (True, 78)),
        ('مقدمه {"score": 0} پایان', (True, 0)),
        ('{"score": 101}', (True, None)),
        ('{"score": 70.5}', (True, None)),
        ('{"score": true}', (True, None)),
        ('{"verdict": "مناسب"}', (True, None)),
        ('{"score": 78', (False, None)),
        ("بدون JSON", (False, None)),
        ("[1, 2]", (False, None)),
    ],
)
def test_parse_score(text, expected):
    assert parse_score(text) == expected


def test_summary_reports_rates_mae_and_constant_baseline():
    labels = [80, 40, 60, 20]
    predictions = [(True, 70), (True, 50), (False, None), (True, None)]
    report = summarize(labels, predictions, baseline=50.0)
    assert report["records"] == 4
    assert report["valid_json_rate"] == 0.75
    assert report["valid_score_rate"] == 0.5
    assert report["mae"] == 10.0
    assert report["baseline_constant_mae"] == 20.0


def test_summary_without_any_valid_score_has_no_mae():
    assert summarize([50], [(False, None)], baseline=50.0)["mae"] is None


def test_file_sizes_are_reported_in_megabytes(tmp_path):
    (tmp_path / "adapter_model.bin").write_bytes(b"\0" * (3 * 1024 * 1024))
    (tmp_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "other.txt").write_text("x", encoding="utf-8")
    assert file_sizes_mb(tmp_path, "adapter_*") == {"adapter_config.json": 0.0, "adapter_model.bin": 3.0}
