"""
دروازه‌ی همگرایی و بیش‌برازش (Overfitting) آموزش LoRA — از روی log_history در trainer_state.json:

    python -m training.lora.check_convergence --state training/outputs/<run>/trainer_state.json \
        --out training/reports/<run>

خروجی: convergence.json (نتیجه‌ی هر بررسی) + loss_curves.png (نمودار loss آموزش و اعتبارسنجی). کد خروج ۱ اگر
هر بررسی رد شود. منطق پایتون خالص است (matplotlib فقط برای نمودار و به‌صورت تنبل import می‌شود).
"""

from __future__ import annotations

import argparse
import json
import sys
import math
from pathlib import Path
from statistics import mean

# کاهش loss آموزش از پنجره‌ی اول ثبت‌شده تا پنجره‌ی آخر (۰٫۴۰ = حداقل ۴۰٪)
MIN_TRAIN_LOSS_DROP = 0.40
# حداکثر فاصله‌ی «بهترین loss اعتبارسنجی − loss آموزش پنجره‌ی آخر»؛ بیشتر = مدل داده‌ی آموزش را حفظ کرده
MAX_EVAL_TRAIN_GAP = 0.35
# این تعداد افزایش پشت‌سرهم loss اعتبارسنجی بعد از بهترین نقطه = بیش‌برازش
MAX_CONSECUTIVE_EVAL_RISES = 3
# تعداد نقطه‌ی loss آموزش که میانگینشان «پنجره»ی اول/آخر است (نویز تک‌دسته‌ها را صاف می‌کند)
TRAIN_WINDOW = 3
MIN_EVAL_POINTS = 3


def _series(history: list[dict], key: str) -> list[tuple[int, float]]:
    return [(int(row["step"]), float(row[key])) for row in history if key in row and "step" in row]


def _longest_rise(values: list[float]) -> int:
    longest = current = 0
    for previous, value in zip(values, values[1:]):
        current = current + 1 if value > previous else 0
        longest = max(longest, current)
    return longest


def _check(value: float, threshold: float, passed: bool) -> dict:
    return {"value": round(value, 4), "threshold": threshold, "passed": bool(passed)}


def evaluate_history(history: list[dict]) -> dict:
    train, evals = _series(history, "loss"), _series(history, "eval_loss")
    if not train or not evals:
        return {"passed": False, "error": "no_train_loss" if not train else "no_eval_loss", "checks": {}}
    if any(not math.isfinite(value) or value < 0 for _, value in train + evals):
        return {"passed": False, "error": "invalid_loss", "checks": {}}
    if len(train) < 2 * TRAIN_WINDOW or len(evals) < MIN_EVAL_POINTS:
        return {"passed": False, "error": "insufficient_history", "checks": {}}
    first_window = mean(value for _, value in train[:TRAIN_WINDOW])
    last_window = mean(value for _, value in train[-TRAIN_WINDOW:])
    eval_values = [value for _, value in evals]
    best_index = min(range(len(eval_values)), key=eval_values.__getitem__)
    best_step, best = evals[best_index]
    drop = 1 - last_window / first_window if first_window else 0.0
    rises = _longest_rise(eval_values[best_index:])
    gap = best - last_window
    checks = {
        "train_loss_drop": _check(drop, MIN_TRAIN_LOSS_DROP, drop >= MIN_TRAIN_LOSS_DROP),
        "eval_improved": _check(best, eval_values[0], best < eval_values[0]),
        "no_consecutive_eval_rise": _check(rises, MAX_CONSECUTIVE_EVAL_RISES, rises < MAX_CONSECUTIVE_EVAL_RISES),
        "eval_train_gap": _check(gap, MAX_EVAL_TRAIN_GAP, gap <= MAX_EVAL_TRAIN_GAP),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "best_eval_loss": round(best, 4),
        "best_eval_step": best_step,
        "first_eval_loss": round(eval_values[0], 4),
        "train_loss_first_window": round(first_window, 4),
        "train_loss_last_window": round(last_window, 4),
        "train_points": len(train),
        "eval_points": len(evals),
    }


def plot_curves(history: list[dict], result: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    train, evals = _series(history, "loss"), _series(history, "eval_loss")
    figure, axis = plt.subplots(figsize=(10, 5.5), dpi=120)
    axis.plot(*zip(*train), label="train loss", color="#3b6fd8", linewidth=1.4)
    axis.plot(*zip(*evals), label="validation loss", color="#d8663b", linewidth=2, marker="o", markersize=4)
    axis.axvline(result["best_eval_step"], color="#2f9e62", linestyle="--", linewidth=1, label="best checkpoint")
    axis.set_xlabel("optimizer step")
    axis.set_ylabel("loss")
    status = "PASS" if result["passed"] else "FAIL"
    title = (
        f"LoRA smoke run — diagnostic {status} (synthetic data; not final acceptance)"
        if result.get("diagnostic_only")
        else f"LoRA training — convergence {status}"
    )
    axis.set_title(title)
    axis.grid(alpha=0.3)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m training.lora.check_convergence")
    parser.add_argument("--state", type=Path, required=True, help="trainer_state.json")
    parser.add_argument("--out", type=Path, required=True, help="پوشه‌ی گزارش")
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--diagnostic", action="store_true", help="برچسب صریح اجرای آزمایشی؛ پذیرش نهایی نیست")
    args = parser.parse_args(argv)
    history = json.loads(args.state.read_text(encoding="utf-8"))["log_history"]
    result = evaluate_history(history)
    if args.diagnostic:
        result["diagnostic_only"] = True
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "convergence.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not args.no_plot and "error" not in result:
        plot_curves(history, result, args.out / "loss_curves.png")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
