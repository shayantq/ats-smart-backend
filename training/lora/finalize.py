"""اعتبارسنجی کامل و خروجی‌گیری از بهترین checkpoint پس از توقف صریح کاربر؛ بدون هیچ گام آموزش."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from training.lora.config import RunConfig, resolve_base_model
from training.lora.resources import check_resources, keep_awake
from training.lora.train import prepare_run
from training.lora.workflow import complete_evaluation, performance_settings, run_command, write_status


def finalization_checkpoint(config: RunConfig) -> tuple[Path, dict]:
    """داده و recipe ثابت، خروجی تازه و وزن بهترین checkpoint داخل همان اجرا الزامی است."""
    if (config.output_dir / "adapter").exists() or (config.report_dir / "run_summary.json").exists():
        raise ValueError("خروجی نهایی از قبل وجود دارد؛ بازنویسی مجاز نیست")
    latest = Path(prepare_run(config, resume=True))
    state = json.loads((latest / "trainer_state.json").read_text(encoding="utf-8"))
    checkpoint = Path(state["best_model_checkpoint"])
    root = (config.output_dir / "checkpoints").resolve()
    if checkpoint.resolve().parent != root or not checkpoint.name.startswith("checkpoint-"):
        raise ValueError("بهترین checkpoint باید داخل همین اجرا باشد")
    required = ("adapter_config.json", "adapter_model.safetensors", "trainer_state.json")
    if not all((checkpoint / name).is_file() and (checkpoint / name).stat().st_size for name in required):
        raise ValueError("فایل‌های بهترین checkpoint کامل نیستند")
    best_state = json.loads((checkpoint / "trainer_state.json").read_text(encoding="utf-8"))
    if not 0 < best_state["global_step"] <= state["global_step"]:
        raise ValueError("گام بهترین checkpoint معتبر نیست")
    if best_state["best_metric"] != state["best_metric"]:
        raise ValueError("متریک بهترین checkpoint با سابقهٔ اجرا همخوان نیست")
    return checkpoint, state


def export_checkpoint(config: RunConfig) -> dict:
    """فقط forward روی validation؛ Trainer.train و optimizer اجرا نمی‌شوند."""
    checkpoint, state = finalization_checkpoint(config)
    print(json.dumps({"host_resources": check_resources(config.output_root, starting=True)}), flush=True)
    fast = config.train.kernel_backend == "liger_bf16"
    if fast:
        from training.lora.kernels import configure_liger

        configure_liger()
    import torch
    from peft import PeftModel
    from transformers import Trainer, TrainerState
    from training.lora.data import ListDataset, PadCollator
    from training.lora.train import (
        _progress_callback,
        discard_unused_training_logits,
        export,
        load_model,
        load_splits,
        load_tokenizer,
        resume_tensorboard_writer,
        training_arguments,
    )

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("اعتبارسنجی این پیکربندی به CUDA و bf16 نیاز دارد")
    if fast:
        torch.cuda.set_per_process_memory_fraction(0.85, 0)
    tokenizer = load_tokenizer(config.base_model)
    splits, counts = load_splits(config, tokenizer)
    torch.cuda.reset_peak_memory_stats()
    model = load_model(config)
    if fast:
        from training.lora.kernels import cast_frozen_embeddings_to_bf16, patch_model

        patch_model(model)
        cast_frozen_embeddings_to_bf16(model)
    model = PeftModel.from_pretrained(model, checkpoint, is_trainable=False)
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise ValueError("همهٔ وزن‌ها در مرحلهٔ ارزیابی نهایی باید منجمد باشند")
    model = discard_unused_training_logits(model, fused_loss=fast)
    os.environ["TENSORBOARD_LOGGING_DIR"] = str(config.logging_dir)
    trainer = Trainer(
        model=model,
        args=training_arguments(config, state["max_steps"]),
        eval_dataset=ListDataset(splits["validation_full"].examples),
        data_collator=PadCollator(tokenizer.pad_token_id, answer_logits_only=config.train.answer_logits_only),
        callbacks=[_progress_callback(state["max_steps"], config.output_root)],
        processing_class=tokenizer,
    )
    trainer.state = TrainerState.load_from_json(str(Path(prepare_run(config, resume=True)) / "trainer_state.json"))
    # سابقهٔ کامل checkpoint آخر حفظ می‌شود؛ نقاط ذخیره‌نشدهٔ پس از آن در نمودار کنار می‌روند.
    latest = Path(prepare_run(config, resume=True))
    writer = resume_tensorboard_writer(trainer, str(latest), config.logging_dir)
    started = time.perf_counter()
    try:
        final_eval = trainer.evaluate(
            ListDataset(splits["validation_full"].examples), metric_key_prefix="validation_full"
        )
    finally:
        if writer is not None:
            writer.close()
    duration = time.perf_counter() - started
    summary = export(config, trainer, tokenizer, counts, 0, final_eval, torch.cuda.max_memory_allocated())
    selected_state = json.loads((checkpoint / "trainer_state.json").read_text(encoding="utf-8"))
    summary.update(
        training_termination="user_requested_checkpoint_finalize",
        planned_optimizer_steps=state["max_steps"],
        planned_training_completed=False,
        checkpoint_epoch=state["epoch"],
        finalization_only=True,
        additional_training_steps=0,
        finalization_source_step=state["global_step"],
        selected_checkpoint=str(checkpoint),
        selected_checkpoint_step=selected_state["global_step"],
        full_validation_duration_seconds=round(duration, 3),
        vram_peak_scope="finalization_only",
    )
    (config.report_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def authorized_finalization(directory: Path, previous: dict) -> bool:
    """شروع با تصمیم کاربر؛ فقط یک تلاش مجدد پس از شکست worker قبل از ایجاد خروجی مجاز است."""
    if previous["stage"] == "stopped_by_user_for_final_evaluation":
        return True
    ledger = directory / "attempts.jsonl"
    if previous["stage"] != "failed" or not ledger.is_file():
        return False
    attempts = [json.loads(row) for row in ledger.read_text(encoding="utf-8-sig").splitlines()]
    failures = [row for row in attempts if row["stage"] == "final_validation_and_export" and row["exit_code"] != 0]
    if len(failures) != 1 or attempts[-1] != failures[-1]:
        return False
    return any(
        json.loads(path.read_text(encoding="utf-8-sig"))["stage"] == "stopped_by_user_for_final_evaluation"
        for path in directory.glob("status-before-finalize-*.json")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m training.lora.finalize")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--performance", choices=("native", "fast"), default="native")
    parser.add_argument("--evaluation-batch-size", type=int, choices=(1, 4), default=1)
    parser.add_argument("--evaluation-limit", type=int, choices=(100, 200), default=200)
    parser.add_argument(
        "--export-only", action="store_true", help="worker اعتبارسنجی کامل و خروجی‌گیری؛ بدون inference تست"
    )
    args = parser.parse_args(argv)
    config = RunConfig(
        base_model=resolve_base_model(None), run_id=args.run_id, train=performance_settings(args.performance)
    ).validate()
    if args.export_only:
        export_checkpoint(config)
        return 0
    directory = config.reports_root / f"{args.run_id}-workflow"
    previous = json.loads((directory / "status.json").read_text(encoding="utf-8-sig"))
    if not authorized_finalization(directory, previous):
        parser.error("خروجی‌گیری این مسیر فقط پس از توقف صریح کاربر برای ارزیابی نهایی مجاز است")
    finalization_checkpoint(config)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    (directory / f"status-before-finalize-{stamp}.json").write_text(json.dumps(previous, indent=2), encoding="utf-8")
    try:
        run_command(
            directory,
            "final_validation_and_export",
            "training.lora.finalize",
            "--run-id",
            args.run_id,
            "--performance",
            args.performance,
            "--export-only",
        )
        return complete_evaluation(args.run_id, directory, args.evaluation_batch_size, args.evaluation_limit)
    except Exception as error:  # noqa: BLE001 — متن داده در وضعیت یا لاگ خطا ثبت نمی‌شود.
        write_status(directory, "failed", error=type(error).__name__, log=str(directory / "workflow.log"))
        return 1


if __name__ == "__main__":
    with keep_awake():
        sys.exit(main())
