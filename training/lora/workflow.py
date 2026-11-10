"""ادامه‌ی محلی مراحل طولانی LoRA با گزارش پایدار و توقف در مرز دوازده‌ساعته."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import asdict, replace

from training.lora.config import RunConfig, TrainSettings, resolve_base_model
from training.lora.data import dataset_fingerprint
from training.lora.resources import keep_awake
from training.lora.train import prepare_run

MAX_TRAIN_HOURS = 12.0


def performance_settings(performance: str) -> TrainSettings:
    if performance == "native":
        return TrainSettings()
    if performance == "fast":
        return replace(TrainSettings(), kernel_backend="liger_bf16")
    raise ValueError("مسیر عملکرد ناشناخته است")


def performance_arguments(performance: str) -> list[str]:
    settings = performance_settings(performance)
    return [
        "--kernel-backend",
        settings.kernel_backend,
        "--batch-size",
        str(settings.batch_size),
        "--grad-accum",
        str(settings.grad_accum),
    ]


def write_status(directory: Path, stage: str, **details) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    status = {"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat(), **details}
    temporary = directory / "status.next"
    temporary.write_text(json.dumps(status, indent=2), encoding="utf-8")
    temporary.replace(directory / "status.json")
    print(json.dumps(status), flush=True)


def model_ready(base_model: str) -> bool:
    directory = Path(base_model)
    manifest = directory / "download_manifest.json"
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    files = data.get("files", {})
    return bool(data.get("verified") and any(name.endswith(".safetensors") for name in files)) and all(
        (directory / name).is_file() and (directory / name).stat().st_size == size for name, size in files.items()
    )


def wait_for_download(base_model: str, directory: Path) -> None:
    """دریافت فعال جداست؛ این پردازه فایل مشترک را دوباره دانلود یا بازنویسی نمی‌کند."""
    deadline = time.monotonic() + 12 * 3600
    while not model_ready(base_model):
        if time.monotonic() >= deadline:
            raise TimeoutError("مهلت انتظار دانلود تمام شد")
        parts = list((Path(base_model) / ".parts").rglob("*.part"))
        # دانلودکننده بعد از مونتاژ، بخش‌ها را حذف می‌کند؛ ناپدیدشدن فایل بین فهرست و stat خطا نیست.
        sizes, updated = [], []
        for path in parts + list(Path(base_model).glob("*.safetensors")):
            try:
                metadata = path.stat()
                sizes.append(metadata.st_size)
                updated.append(metadata.st_mtime)
            except FileNotFoundError:
                continue
        downloaded = sum(sizes)
        latest = max(updated, default=time.time())
        if parts and time.time() - latest > 300:
            raise TimeoutError("دریافت برای پنج دقیقه پیشرفت نداشته است؛ بخش‌ها حفظ شدند")
        write_status(directory, "waiting_for_download", downloaded_mib=round(downloaded / 1024**2, 1))
        time.sleep(30)


def run_command(directory: Path, stage: str, module: str, *arguments: str) -> None:
    write_status(directory, stage)
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    started = time.monotonic()
    with (directory / "workflow.log").open("a", encoding="utf-8") as log:
        result = subprocess.run(
            [sys.executable, "-u", "-m", module, *arguments],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
        )
    append_attempt(directory, stage, time.monotonic() - started, result.returncode)
    if result.returncode:
        raise RuntimeError(f"{stage}: exit={result.returncode}")


def append_attempt(directory: Path, stage: str, seconds: float, exit_code: int) -> None:
    with (directory / "attempts.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"stage": stage, "duration_seconds": seconds, "exit_code": exit_code}) + "\n")


def processing_hours(directory: Path) -> float:
    path = directory / "attempts.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return sum(json.loads(row)["duration_seconds"] for row in rows) / 3600


def prepare_failed_resume(directory: Path, config: RunConfig) -> int:
    """workflow شکست‌خورده یا متوقف‌شدهٔ کاربر با داده و recipe یکسان ادامه می‌یابد؛ سابقه حفظ می‌شود."""
    path = directory / "status.json"
    previous = json.loads(path.read_text(encoding="utf-8"))
    if previous["stage"] not in {"failed", "paused_by_user"}:
        raise ValueError("فقط workflow شکست‌خورده یا متوقف‌شدهٔ کاربر قابل ادامه است؛ اجرای فعال یا کامل حفظ می‌شود")
    if previous["stage"] == "paused_by_user" and not (directory / "attempts.jsonl").is_file():
        raise ValueError("سابقهٔ زمان فعال توقف کاربر موجود نیست؛ زمان جابه‌جایی نباید زمان آموزش شمرده شود")
    if (config.report_dir / "run_summary.json").exists():
        raise ValueError("آموزش خروجی نهایی دارد؛ مراحل پس از آموزش باید جداگانه بررسی شوند")
    checkpoint = prepare_run(config, resume=True)
    state = json.loads((Path(checkpoint) / "trainer_state.json").read_text(encoding="utf-8"))
    required = ("adapter_model.safetensors", "optimizer.pt", "scheduler.pt", "rng_state.pth")
    if not all((Path(checkpoint) / name).is_file() and (Path(checkpoint) / name).stat().st_size for name in required):
        raise ValueError("فایل‌های لازم برای ادامهٔ دقیق checkpoint کامل نیستند")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    (directory / f"status-before-resume-{stamp}.json").write_text(json.dumps(previous, indent=2), encoding="utf-8")
    # نسخهٔ نخست ledger نداشت؛ زمان فعال آن از شروع تا ثبت شکست، بدون فاصلهٔ انتظار صبح محاسبه می‌شود.
    if not (directory / "attempts.jsonl").exists():
        original = json.loads((directory / "process.json").read_text(encoding="utf-8-sig"))
        seconds = (
            datetime.fromisoformat(previous["updated_at"]) - datetime.fromisoformat(original["started_at"])
        ).total_seconds()
        if seconds < 0:
            raise ValueError("ترتیب زمانی اجرای قبلی معتبر نیست")
        append_attempt(directory, "previous_workflow_attempt", seconds, 1)
    return state["global_step"]


def verified_smoke(smoke_id: str, performance: str = "native") -> dict:
    """اجرای آزمایشی قبلی فقط با همان مدل، داده و تنظیمات اصلی قابل استفاده است."""
    current = RunConfig(
        base_model=resolve_base_model(None), run_id=smoke_id, train=performance_settings(performance)
    ).validate()
    output = current.output_dir
    summary = json.loads((current.report_dir / "run_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    expected = json.loads(json.dumps(asdict(current), default=str))
    actual = summary["config"]
    actual["train"].setdefault("kernel_backend", "native")
    if summary.get("run_kind") != "smoke" or summary.get("global_steps") != 30:
        raise ValueError("نتیجه‌ی آزمایشی سی‌گامی کامل نیست")
    if manifest["dataset"] != dataset_fingerprint(current.data_dir):
        raise ValueError("دیتاست پس از اجرای آزمایشی تغییر کرده است")
    for field in ("base_model", "data_dir", "lora", "quant"):
        if actual[field] != expected[field]:
            raise ValueError("مدل یا تنظیمات آزمایشی با اجرای کامل یکی نیست")
    diagnostics = {"smoke", "max_steps", "eval_subset", "eval_steps", "logging_steps"}
    for key, value in expected["train"].items():
        if key not in diagnostics and actual["train"][key] != value:
            raise ValueError("هایپرپارامترهای اصلی پس از اجرای آزمایشی تغییر کرده‌اند")
    return summary


def finish_training(
    run_id: str,
    directory: Path,
    smoke_run_id: str | None = None,
    performance: str = "native",
    evaluation_batch_size: int = 1,
    resume: bool = False,
) -> int:
    smoke_id = smoke_run_id or f"{run_id}-smoke"
    run_command(directory, "gpu_check", "training.lora.gpu_check")
    training_args = performance_arguments(performance)
    if performance == "fast":
        run_command(directory, "kernel_check", "training.lora.kernels", "--bf16-embeddings")
    if smoke_run_id:
        smoke = verified_smoke(smoke_id, performance)
    else:
        run_command(directory, "smoke", "training.lora.train", "--run-id", smoke_id, "--smoke", *training_args)
        smoke = json.loads((Path("training/reports") / smoke_id / "run_summary.json").read_text(encoding="utf-8"))
    estimate = smoke.get("timing", {}).get("estimated_full_run_hours")
    if resume:
        config = RunConfig(base_model=resolve_base_model(None), run_id=run_id, train=performance_settings(performance))
        checkpoint = prepare_run(config, resume=True)
        step = json.loads((Path(checkpoint) / "trainer_state.json").read_text(encoding="utf-8"))["global_step"]
        timing = smoke["timing"]
        final_seconds = timing["final_validation_seconds_estimate"]
        validation_count = smoke["data"]["validation_full"]["kept"]
        evals_left = timing["full_optimizer_steps"] // 50 - step // 50
        remaining_seconds = (
            (timing["full_optimizer_steps"] - step) * timing["optimizer_step_seconds_median"]
            + evals_left * final_seconds * 300 / validation_count
            + final_seconds
        )
        estimate = processing_hours(directory) + remaining_seconds / 3600
        write_status(directory, "resume_preflight", checkpoint_step=step, projected_total_training_hours=estimate)
    if not isinstance(estimate, (int, float)) or not math.isfinite(estimate) or not 0 < estimate <= MAX_TRAIN_HOURS:
        write_status(directory, "needs_training_approval", estimated_hours=estimate, limit_hours=MAX_TRAIN_HOURS)
        return 3
    resume_args = ["--resume"] if resume else []
    run_command(directory, "training", "training.lora.train", "--run-id", run_id, *training_args, *resume_args)
    return complete_evaluation(run_id, directory, evaluation_batch_size)


def complete_evaluation(
    run_id: str, directory: Path, evaluation_batch_size: int = 1, evaluation_limit: int = 200
) -> int:
    """پذیرش یکسان برای پایان عادی آموزش و خروجی‌گیری از checkpoint توقف کاربر."""
    output, report = Path("training/outputs") / run_id, Path("training/reports") / run_id
    # نتیجه‌ی ردشدن همگرایی باید ثبت شود، اما آداپتر همچنان برای بررسی مستقل قابل ارزیابی است.
    try:
        run_command(
            directory,
            "convergence",
            "training.lora.check_convergence",
            "--state",
            str(output / "trainer_state.json"),
            "--out",
            str(report),
        )
    except RuntimeError:
        if not (report / "convergence.json").is_file():
            raise
    run_command(
        directory,
        "evaluation",
        "training.lora.evaluate",
        "--adapter",
        str(output / "adapter"),
        "--report",
        str(report / "evaluation.json"),
        "--batch-size",
        str(evaluation_batch_size),
        "--limit",
        str(evaluation_limit),
    )
    convergence = json.loads((report / "convergence.json").read_text(encoding="utf-8"))
    evaluation = json.loads((report / "evaluation.json").read_text(encoding="utf-8"))
    summary = json.loads((report / "run_summary.json").read_text(encoding="utf-8"))
    summary["workflow_processing_hours"] = round(processing_hours(directory), 3)
    (report / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    passed = bool(
        convergence["passed"]
        and summary["full_validation_completed"]
        and evaluation["adapter_reloaded"]
        and evaluation["adapter_base_size_ratio"] is not None
        and evaluation["adapter_base_size_ratio"] < 0.1
    )
    write_status(
        directory,
        "completed" if passed else "acceptance_failed",
        report_dir=str(report),
        best_eval_loss=summary["best_eval_loss"],
        adapter_weights_bytes=evaluation["adapter_weights_bytes"],
        adapter_base_size_ratio=evaluation["adapter_base_size_ratio"],
        valid_score_rate=evaluation["valid_score_rate"],
        mae=evaluation["mae"],
        training_termination=summary.get("training_termination", "trainer_finished"),
        global_steps=summary["global_steps"],
        planned_training_completed=summary.get("planned_training_completed", True),
    )
    append_measured_results(run_id, summary, convergence, evaluation)
    return 0 if passed else 1


def append_measured_results(run_id: str, summary: dict, convergence: dict, evaluation: dict) -> None:
    path = Path("docs/finetune/LORA.md")
    duration_note = (
        "مرحلهٔ نهایی بدون گام آموزش تازه"
        if summary.get("finalization_only")
        else f"مدت آموزش همین نوبت: {summary['train_duration_hours']} ساعت"
    )
    source_step = summary.get("finalization_source_step", summary.get("resumed_from_step", 0))
    block = (
        f"\n### نتیجه‌ی اندازه‌گیری‌شده‌ی اجرای `{run_id}`\n\n"
        "این اجرا روی دیتاست ساختگی است و شاهد کیفیت روی بازار کار واقعی نیست.\n\n"
        f"- گام واقعی: {summary['global_steps']}؛ {duration_note}.\n"
        f"- علت پایان: {summary.get('training_termination', 'trainer_finished')}؛ "
        f"تکمیل برنامهٔ اولیهٔ آموزش: {summary.get('planned_training_completed', True)}.\n"
        f"- مجموع زمان فعال workflow با تلاش‌های قبلی: {summary.get('workflow_processing_hours')} ساعت؛ "
        f"مبنای ادامه یا خروجی‌گیری: گام {source_step}.\n"
        f"- بهترین loss اعتبارسنجی: {summary['best_eval_loss']}؛ دروازه‌ی همگرایی: {convergence['passed']}.\n"
        f"- اندازه‌ی وزن آداپتر: {evaluation['adapter_weights_bytes']} بایت؛ "
        f"نسبت به وزن پایه: {evaluation['adapter_base_size_ratio']}.\n"
        f"- نرخ نمره‌ی معتبر: {evaluation['valid_score_rate']}؛ MAE مشروط به پاسخ معتبر: {evaluation['mae']}.\n"
        f"- تعداد نمونه‌های تست: {evaluation['records']}؛ نرخ JSON معتبر: {evaluation['valid_json_rate']}.\n"
        f"- شواهد: `training/reports/{run_id}/` و `training/outputs/{run_id}/adapter/`.\n"
    )
    with path.open("a", encoding="utf-8", newline="\n") as document:
        document.write(block)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m training.lora.workflow")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--wait-download", action="store_true")
    parser.add_argument("--smoke-run-id", help="استفاده از نتیجه‌ی سی‌گامی تأییدشده، به‌جای اجرای تکراری")
    parser.add_argument("--performance", choices=("native", "fast"), default="native")
    parser.add_argument("--evaluation-batch-size", type=int, choices=(1, 4), default=1)
    parser.add_argument(
        "--resume", action="store_true", help="ادامهٔ workflow شکست‌خورده یا متوقف‌شده از آخرین checkpoint"
    )
    args = parser.parse_args(argv)
    config = RunConfig(
        base_model=resolve_base_model(None), run_id=args.run_id, train=performance_settings(args.performance)
    ).validate()
    directory = Path("training/reports") / f"{args.run_id}-workflow"
    if (directory / "status.json").exists() and not args.resume:
        parser.error("این workflow قبلاً شروع شده؛ وضعیت قبلی را بررسی یا run-id تازه انتخاب کنید")
    if args.resume:
        try:
            prepare_failed_resume(directory, config)
        except (ValueError, FileNotFoundError) as error:
            parser.error(str(error))
    try:
        if args.wait_download:
            wait_for_download(config.base_model, directory)
        if not model_ready(config.base_model):
            raise ValueError("دانلود تأییدشده‌ی مدل هنوز کامل نیست")
        return finish_training(
            args.run_id, directory, args.smoke_run_id, args.performance, args.evaluation_batch_size, args.resume
        )
    except Exception as error:  # noqa: BLE001 — متن داده یا URL سرویس در خروجی ثبت نمی‌شود
        write_status(directory, "failed", error=type(error).__name__, log=str(directory / "workflow.log"))
        return 1


if __name__ == "__main__":
    with keep_awake():
        sys.exit(main())
