"""
تست‌های پیکربندی LoRA و دروازه‌ی همگرایی/بیش‌برازش (training/lora/config.py و check_convergence.py).
هر دو ماژول پایتون خالص‌اند و در CI (بدون torch) هم اجرا می‌شوند.
"""

import json

import pytest

from training.lora.check_convergence import (
    MAX_EVAL_TRAIN_GAP,
    MIN_TRAIN_LOSS_DROP,
    evaluate_history,
    main as convergence_main,
)
from training.lora.config import LoraSettings, RunConfig, TrainSettings, load_env_file

TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


# ---------------------------------------------------------------------------
# پیکربندی
# ---------------------------------------------------------------------------
def test_defaults_match_the_specified_hyperparameters():
    lora, train = LoraSettings(), TrainSettings()
    assert (lora.r, lora.alpha, lora.dropout, lora.bias) == (16, 32, 0.05, "none")
    assert lora.target_modules == TARGETS
    assert (train.max_seq_len, train.batch_size, train.grad_accum) == (2048, 1, 16)
    assert (train.learning_rate, train.scheduler, train.warmup_ratio, train.epochs) == (2e-4, "cosine", 0.03, 2)
    assert (train.eval_steps, train.eval_subset, train.early_stopping_patience, train.save_total_limit) == (
        50,
        300,
        3,
        2,
    )
    assert train.optimizer == "paged_adamw_8bit" and train.gradient_checkpointing


@pytest.mark.parametrize(
    "lora",
    [
        {"r": 0},
        {"alpha": 0},
        {"dropout": 1.0},
        {"dropout": -0.1},
        {"target_modules": ()},
        {"bias": "everything"},
    ],
)
def test_invalid_lora_settings_are_rejected(lora):
    with pytest.raises(ValueError):
        RunConfig(base_model="models/base", lora=LoraSettings(**lora)).validate()


@pytest.mark.parametrize(
    "train", [{"max_seq_len": 0}, {"grad_accum": 0}, {"learning_rate": 0}, {"warmup_ratio": 1.5}, {"eval_subset": 0}]
)
def test_invalid_train_settings_are_rejected(train):
    with pytest.raises(ValueError):
        RunConfig(base_model="models/base", train=TrainSettings(**train)).validate()


def test_base_model_is_required():
    with pytest.raises(ValueError):
        RunConfig(base_model="").validate()


def test_settings_are_immutable():
    with pytest.raises(Exception):
        LoraSettings().r = 8  # type: ignore[misc]


def test_env_file_is_parsed_without_exporting_comments(tmp_path):
    path = tmp_path / "model.env"
    path.write_text("# توضیح\nLORA_BASE_MODEL=org/name\nEMPTY=\n", encoding="utf-8")
    assert load_env_file(path) == {"LORA_BASE_MODEL": "org/name", "EMPTY": ""}
    assert load_env_file(tmp_path / "missing.env") == {}


# ---------------------------------------------------------------------------
# دروازه‌ی همگرایی
# ---------------------------------------------------------------------------
def _history(train: list[float], evals: list[float], every: int = 10) -> list[dict]:
    rows = [{"step": (i + 1) * every, "loss": value} for i, value in enumerate(train)]
    eval_every = len(train) * every // max(1, len(evals))
    rows += [{"step": (i + 1) * eval_every, "eval_loss": value} for i, value in enumerate(evals)]
    return sorted(rows, key=lambda row: row["step"])


def test_converging_run_passes():
    train = [2.4, 2.1, 1.8, 1.2, 0.9, 0.7, 0.6, 0.55, 0.52, 0.5]
    result = evaluate_history(_history(train, [1.0, 0.75, 0.66, 0.62, 0.61]))
    assert result["passed"], result
    assert result["best_eval_loss"] == 0.61


def test_flat_training_loss_fails_the_drop_check():
    result = evaluate_history(_history([2.0] * 10, [1.9, 1.85, 1.8]))
    assert not result["passed"]
    assert not result["checks"]["train_loss_drop"]["passed"]
    assert result["checks"]["train_loss_drop"]["threshold"] == MIN_TRAIN_LOSS_DROP


def test_rising_eval_loss_is_overfitting():
    train = [2.4, 2.0, 1.5, 1.0, 0.6, 0.3, 0.2, 0.15, 0.12, 0.1]
    result = evaluate_history(_history(train, [1.0, 0.7, 0.75, 0.8, 0.9, 1.0]))
    assert not result["passed"]
    assert not result["checks"]["no_consecutive_eval_rise"]["passed"]


def test_large_generalization_gap_is_overfitting():
    train = [2.4, 2.0, 1.5, 1.0, 0.6, 0.3, 0.2, 0.15, 0.12, 0.1]
    result = evaluate_history(_history(train, [1.2, 0.9, 0.85, 0.8]))
    assert not result["checks"]["eval_train_gap"]["passed"]
    assert result["checks"]["eval_train_gap"]["threshold"] == MAX_EVAL_TRAIN_GAP


def test_missing_eval_entries_fail_clearly():
    result = evaluate_history(_history([2.0, 1.0, 0.5], []))
    assert not result["passed"]
    assert result["error"] == "no_eval_loss"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_non_finite_or_negative_loss_is_rejected(value):
    result = evaluate_history(_history([2.0] * 6, [1.8, value, 1.5]))
    assert not result["passed"] and result["error"] == "invalid_loss"


def test_one_eval_point_cannot_prove_convergence():
    result = evaluate_history(_history([2.0, 1.8, 1.6, 0.8, 0.7, 0.6], [0.7]))
    assert not result["passed"] and result["error"] == "insufficient_history"


def test_validation_that_never_improves_does_not_pass():
    result = evaluate_history(_history([2.0, 1.8, 1.6, 0.8, 0.7, 0.6], [0.7, 0.7, 0.7]))
    assert not result["checks"]["eval_improved"]["passed"]


def test_cli_writes_report_and_exit_code(tmp_path):
    train = [2.4, 2.1, 1.8, 1.2, 0.9, 0.7, 0.6, 0.55, 0.52, 0.5]
    state = tmp_path / "trainer_state.json"
    state.write_text(json.dumps({"log_history": _history(train, [1.0, 0.75, 0.66, 0.62, 0.61])}), encoding="utf-8")
    out = tmp_path / "report"
    assert convergence_main(["--state", str(state), "--out", str(out), "--no-plot"]) == 0
    assert json.loads((out / "convergence.json").read_text(encoding="utf-8"))["passed"] is True

    state.write_text(json.dumps({"log_history": _history([2.0] * 10, [1.9, 1.8])}), encoding="utf-8")
    assert convergence_main(["--state", str(state), "--out", str(out), "--no-plot"]) == 1
