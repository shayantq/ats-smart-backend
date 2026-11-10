"""بنچمارک محدود محلی برای انتخاب مسیر سریع‌تر؛ جای smoke سی‌گامی یا آموزش کامل نیست."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from dataclasses import replace
from statistics import median
from types import SimpleNamespace

from training.lora.config import RunConfig, TrainSettings, resolve_base_model
from training.lora.data import ListDataset, PadCollator
from training.lora.resources import check_resources
from training.lora.train import (
    _progress_callback,
    apply_lora,
    discard_unused_training_logits,
    load_model,
    load_splits,
    load_tokenizer,
    prepare_run,
    timing_report,
    training_arguments,
    verify_target_modules,
)

BENCHMARK_LIMIT_SECONDS = 600
OPTIMIZERS = ("paged_adamw_8bit", "adamw_8bit")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--optimizer", choices=OPTIMIZERS, default=OPTIMIZERS[0])
    parser.add_argument("--steps", type=int, choices=range(3, 9), default=4)
    parser.add_argument("--empty-cache-steps", type=int, choices=(1, 4, 16), default=1)
    parser.add_argument("--eval-records", type=int, choices=(30, 300), default=30)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--kernels", choices=("native", "liger"), default="native")
    parser.add_argument("--batch-size", type=int, choices=(1, 2, 4, 8), default=1)
    parser.add_argument("--bf16-embeddings", action="store_true")
    parser.add_argument("--gpu-memory-fraction", type=float)
    args = parser.parse_args(argv)
    if args.gpu_memory_fraction is not None and (
        not math.isfinite(args.gpu_memory_fraction) or not 0 < args.gpu_memory_fraction <= 1
    ):
        parser.error("سهم حافظهٔ GPU باید عدد محدود در بازهٔ (0, 1] باشد")
    return args


def run(args) -> dict:
    print(json.dumps({"host_resources": check_resources(RunConfig(base_model="local").output_root, starting=True)}))
    if args.kernels == "liger":
        from training.lora.kernels import configure_liger

        configure_liger()
    import torch
    from transformers import Trainer, TrainerCallback, set_seed

    settings = replace(
        TrainSettings(),
        smoke=True,
        max_steps=args.steps,
        eval_steps=args.steps,
        eval_subset=args.eval_records,
        logging_steps=1,
        optimizer=args.optimizer,
        batch_size=args.batch_size,
        grad_accum=16 // args.batch_size,
    )
    config = RunConfig(base_model=resolve_base_model(None), run_id=args.run_id, train=settings).validate()
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("این بنچمارک به CUDA و bf16 نیاز دارد")
    if args.gpu_memory_fraction is not None:
        torch.cuda.set_per_process_memory_fraction(args.gpu_memory_fraction, 0)
    set_seed(settings.seed)
    tokenizer = load_tokenizer(config.base_model)
    splits, counts = load_splits(config, tokenizer)
    prepare_run(config, resume=False)
    config.report_dir.mkdir(parents=True, exist_ok=True)
    torch.cuda.reset_peak_memory_stats()
    model = load_model(config)
    if args.kernels == "liger":
        from training.lora.kernels import patch_model

        patch_model(model)
    if args.bf16_embeddings:
        from training.lora.kernels import cast_frozen_embeddings_to_bf16

        cast_frozen_embeddings_to_bf16(model)
    check_resources(config.output_root)
    verify_target_modules(model, config.lora.target_modules)
    set_seed(settings.seed)
    model = discard_unused_training_logits(apply_lora(model, config.lora), fused_loss=args.kernels == "liger")
    arguments = training_arguments(config, settings.max_steps)
    # فقط در بنچمارک ذخیره/ارزیابی خودکار خاموش است؛ معیارهای اجرای اصلی تغییر نمی‌کنند.
    arguments.eval_strategy = "no"
    arguments.save_strategy = "no"
    arguments.load_best_model_at_end = False
    arguments.report_to = []
    arguments.torch_empty_cache_steps = args.empty_cache_steps
    progress = _progress_callback(settings.max_steps, config.output_root)
    started = time.perf_counter()

    class Probe(TrainerCallback):
        def __init__(self):
            self.profiler = None

        def check_deadline(self):
            if time.perf_counter() - started > BENCHMARK_LIMIT_SECONDS:
                raise TimeoutError("مهلت ده‌دقیقه‌ای بنچمارک تمام شد؛ اجرای کامل آغاز نشده است")

        def on_train_begin(self, *unused, **kwargs):
            if args.profile:
                self.profiler = torch.profiler.profile(
                    activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA],
                    record_shapes=False,
                    profile_memory=False,
                    with_stack=False,
                )
                self.profiler.__enter__()

        def finish_profile(self):
            if self.profiler is not None:
                profiler, self.profiler = self.profiler, None
                profiler.__exit__(None, None, None)
                grouped = {}
                # تجمیع مستقیم رویدادهای CUDA؛ محاسبهٔ بازگشتی key_averages سربار زیادی داشت.
                for event in profiler.events():
                    row = grouped.setdefault(
                        event.name,
                        {
                            "operator": event.name,
                            "calls": 0,
                            "cpu_self_us": 0,
                            "device_self_us": 0,
                        },
                    )
                    row["calls"] += 1
                    if str(event.device_type).endswith("CUDA"):
                        row["device_self_us"] += event.time_range.elapsed_us()
                    else:
                        row["cpu_self_us"] += event.self_cpu_time_total
                events = list(grouped.values())
                events.sort(key=lambda event: event["device_self_us"], reverse=True)
                (config.report_dir / "operators.json").write_text(json.dumps(events[:40], indent=2), encoding="utf-8")

        def on_step_end(self, *unused, **kwargs):
            self.finish_profile()
            self.check_deadline()

        def on_substep_end(self, *unused, **kwargs):
            # ثبت کل ۱۶ ریزگام روی ویندوز سربار بالایی داشت؛ یک ریزگام نماینده کافی است.
            self.finish_profile()
            self.check_deadline()

        def on_prediction_step(self, *unused, **kwargs):
            self.check_deadline()

    probe = Probe()
    trainer = Trainer(
        model=model,
        args=arguments,
        train_dataset=ListDataset(splits["train"].examples),
        eval_dataset=ListDataset(splits["eval_subset"].examples),
        data_collator=PadCollator(tokenizer.pad_token_id, answer_logits_only=True),
        callbacks=[progress, probe],
        processing_class=tokenizer,
    )
    # فقط سنجه‌های عددی دستگاه؛ متن داده و متغیرهای محیطی وارد trace نمی‌شوند.
    telemetry_file = (config.report_dir / "gpu.csv").open("w", encoding="utf-8")
    telemetry = subprocess.Popen(
        [
            "nvidia-smi",
            "--query-gpu=timestamp,pstate,utilization.gpu,utilization.memory,"
            "memory.used,clocks.sm,power.draw,temperature.gpu",
            "--format=csv",
            "--loop-ms=2000",
        ],
        stdout=telemetry_file,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        trainer.train()
        # تکرار روی همان رکوردها برای آشکارشدن نوسان؛ هیچ رکورد test مصرف نمی‌شود.
        evaluations = [trainer.evaluate() for _ in range(2)]
    finally:
        probe.finish_profile()
        if telemetry.poll() is None:
            telemetry.terminate()
            telemetry.wait(timeout=5)
        telemetry_file.close()
    report = {
        "run_kind": "microbenchmark",
        "final_acceptance": False,
        "synthetic_data": True,
        "optimizer": settings.optimizer,
        "kernels": args.kernels,
        "batch_size": settings.batch_size,
        "gradient_accumulation": settings.grad_accum,
        "effective_batch_size": settings.batch_size * settings.grad_accum,
        "embedding_dtype": "bfloat16" if args.bf16_embeddings else "float32",
        "response_rows_compacted": args.kernels == "liger",
        "gpu_memory_fraction": args.gpu_memory_fraction,
        "empty_cache_steps": args.empty_cache_steps,
        "profiled_first_optimizer_step": args.profile,
        "model_accepts_loss_kwargs": trainer.model_accepts_loss_kwargs,
        "adapter_initialization_seed": settings.seed,
        "optimizer_steps": trainer.state.global_step,
        "optimizer_step_seconds": progress.step_seconds,
        "steady_step_seconds_median": median(progress.step_seconds[1:]),
        "validation": evaluations,
        "timing_estimate": timing_report(config, progress, len(splits["train"].examples)),
        "steady_timing_estimate": timing_report(
            config,
            SimpleNamespace(step_seconds=progress.step_seconds[1:], eval_seconds=progress.eval_seconds),
            len(splits["train"].examples),
        ),
        "peak_allocated_gib": torch.cuda.max_memory_allocated() / 1024**3,
        "peak_reserved_gib": torch.cuda.max_memory_reserved() / 1024**3,
        "data": counts,
        "host_resources_after": check_resources(config.output_root),
        "attention_backend": model.config._attn_implementation,
        "elapsed_seconds": time.perf_counter() - started,
    }
    (config.report_dir / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return report


def main(argv=None):
    run(parse_args(argv))


if __name__ == "__main__":
    main()
