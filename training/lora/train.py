"""
آموزش تکمیلی QLoRA روی دیتاست ATS:

    python -m training.lora.train --run-id smoke --smoke                           # اجرای آزمایشی
    python -m training.lora.train --run-id main                                      # اجرای کامل
    python -m training.lora.train --run-id main --resume                             # ادامه پس از قطعی

مدل پایه با وزن ۴ بیتی NF4 بارگذاری و فقط ماتریس‌های کم‌رتبه‌ی LoRA آموزش داده می‌شوند. loss فقط روی پاسخ
(assistant)، eval میانی روی زیرمجموعه‌ی ثابت validation، توقف زودهنگام روی eval_loss و بارگذاری بهترین
checkpoint در پایان. پایش زنده: tensorboard --logdir training/runs
خروجی: training/outputs/<run>/adapter (adapter_config.json + adapter_model.bin) و training/reports/<run>.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import hashlib
from functools import wraps
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from statistics import median

from training.lora.config import LoraSettings, RunConfig, TrainSettings, resolve_base_model
from training.lora.resources import check_resources, keep_awake
from training.lora.data import (
    ListDataset,
    PadCollator,
    audited_records,
    dataset_fingerprint,
    encode_split,
    stratified_subset,
)

ADAPTER_DIR = "adapter"
CHECKPOINT_DIR = "checkpoints"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    defaults_lora, defaults_train = LoraSettings(), TrainSettings()
    parser = argparse.ArgumentParser(prog="python -m training.lora.train")
    parser.add_argument("--base-model", default=None, help="مسیر/شناسه‌ی مدل پایه (پیش‌فرض: LORA_BASE_MODEL)")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/finetune"))
    parser.add_argument("--resume", action="store_true", help="ادامه از آخرین checkpoint همین run-id")
    parser.add_argument("--smoke", action="store_true", help="۳۰ گام آزمایشی؛ معیار تکمیل آموزش نیست")
    parser.add_argument("--r", type=int, default=defaults_lora.r)
    parser.add_argument("--alpha", type=int, default=defaults_lora.alpha)
    parser.add_argument("--dropout", type=float, default=defaults_lora.dropout)
    for name in ("max_seq_len", "grad_accum", "epochs", "eval_steps", "eval_subset", "logging_steps", "max_steps"):
        parser.add_argument(f"--{name.replace('_', '-')}", type=int, default=getattr(defaults_train, name))
    parser.add_argument("--learning-rate", type=float, default=defaults_train.learning_rate)
    parser.add_argument("--batch-size", type=int, default=defaults_train.batch_size)
    parser.add_argument("--kernel-backend", choices=("native", "liger_bf16"), default="native")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> RunConfig:
    lora = replace(LoraSettings(), r=args.r, alpha=args.alpha, dropout=args.dropout)
    names = ("max_seq_len", "grad_accum", "epochs", "eval_steps", "eval_subset", "logging_steps", "max_steps")
    train = replace(
        TrainSettings(),
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
        kernel_backend=args.kernel_backend,
        **{name: getattr(args, name) for name in names},
    )
    if args.smoke:
        train = replace(train, smoke=True, max_steps=30, eval_steps=10, eval_subset=30)
    config = RunConfig(base_model=resolve_base_model(args.base_model), run_id=args.run_id, data_dir=args.data_dir)
    return replace(config, lora=lora, train=train).validate()


def load_tokenizer(base_model: str):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def load_splits(config: RunConfig, tokenizer) -> tuple[dict, dict]:
    from tokenizers import Tokenizer

    records, audit = audited_records(config.data_dir)
    reference = config.data_dir.parent / "tokenizer" / "tokenizer.json"
    stats = json.loads((config.data_dir / "stats.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    if digest[:16] != stats["tokenizer_sha256"]:
        raise ValueError("توکنایزر مرجع با توکنایزر اعتبارسنجی دیتاست یکی نیست")
    if Tokenizer.from_file(str(reference)).get_vocab() != tokenizer.get_vocab():
        raise ValueError("واژگان توکنایزر مدل پایه با دیتاست یکی نیست؛ مدل را بی‌صدا عوض نکنید")
    train_records, validation_records = records["train"], records["validation"]
    subset = stratified_subset(validation_records, config.train.eval_subset, config.train.seed)
    splits = {
        "train": encode_split(tokenizer, train_records, config.train.max_seq_len),
        "eval_subset": encode_split(tokenizer, subset, config.train.max_seq_len),
        "validation_full": encode_split(tokenizer, validation_records, config.train.max_seq_len),
    }
    counts = {
        name: {"kept": len(split.examples), "dropped_too_long": split.dropped_too_long}
        for name, split in splits.items()
    }
    if any(not split.examples for split in splits.values()):
        raise ValueError("پس از توکن‌سازی یک بخش از داده خالی است")
    print(json.dumps({"data": counts, "audit": audit}, ensure_ascii=False), flush=True)
    return splits, counts


def load_model(config: RunConfig):
    import torch
    from peft import prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type=config.quant.quant_type,
        bnb_4bit_use_double_quant=config.quant.double_quant,
        bnb_4bit_compute_dtype=getattr(torch, config.quant.compute_dtype),
    )
    model = AutoModelForCausalLM.from_pretrained(
        config.base_model, quantization_config=quantization, dtype=torch.bfloat16, device_map={"": 0}
    )
    model.config.use_cache = False
    return prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=config.train.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )


def verify_target_modules(model, targets: tuple[str, ...]) -> dict[str, int]:
    """هر ماژول هدف LoRA باید واقعاً در معماری مدل پایه وجود داشته باشد — وگرنه آموزش بی‌صدا ناقص می‌شود."""
    counts = {target: 0 for target in targets}
    for name, _ in model.named_modules():
        leaf = name.rsplit(".", 1)[-1]
        if leaf in counts:
            counts[leaf] += 1
    missing = [target for target, count in counts.items() if count == 0]
    if missing:
        raise ValueError(f"ماژول‌های هدف LoRA در مدل پایه وجود ندارند: {missing}")
    print(json.dumps({"lora_target_modules": counts}), flush=True)
    return counts


def apply_lora(model, settings: LoraSettings):
    from peft import LoraConfig, get_peft_model

    lora_config = LoraConfig(
        r=settings.r,
        lora_alpha=settings.alpha,
        lora_dropout=settings.dropout,
        bias=settings.bias,
        target_modules=list(settings.target_modules),
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    validate_trainable_parameters(model)
    trainable, total = model.get_nb_trainable_parameters()
    print(
        json.dumps(
            {"trainable_params": trainable, "total_params": total, "trainable_pct": round(100 * trainable / total, 3)}
        )
    )
    return model


def validate_trainable_parameters(model) -> None:
    """وزن‌های پایه باید واقعاً منجمد باشند؛ فقط ماتریس‌های آداپتر آموزش می‌بینند."""
    names = [name for name, parameter in model.named_parameters() if parameter.requires_grad]
    if not names or any("lora_A" not in name and "lora_B" not in name for name in names):
        raise ValueError("پارامترهای قابل آموزش به ماتریس‌های LoRA محدود نیستند")


def discard_unused_training_logits(model, *, fused_loss: bool = False):
    """پس از ساخت loss، logits مصرف‌نشده پیش از تبدیل خروجی‌ها به FP32 در Accelerate آزاد می‌شوند."""
    original_forward = model.forward

    @wraps(original_forward)
    def forward(*args, **kwargs):
        if fused_loss and kwargs.get("labels") is not None:
            kwargs["skip_logits"] = True
        output = original_forward(*args, **kwargs)
        loss = getattr(output, "loss", None)
        return {"loss": loss} if loss is not None else output

    model.forward = forward
    return model


def total_optimizer_steps(config: RunConfig, train_examples: int) -> int:
    if config.train.max_steps > 0:
        return config.train.max_steps
    per_epoch = math.ceil(train_examples / (config.train.batch_size * config.train.grad_accum))
    return per_epoch * config.train.epochs


def training_arguments(config: RunConfig, total_steps: int):
    from transformers import TrainingArguments

    train = config.train
    return TrainingArguments(
        output_dir=str(config.output_dir / CHECKPOINT_DIR),
        per_device_train_batch_size=train.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=train.grad_accum,
        learning_rate=train.learning_rate,
        lr_scheduler_type=train.scheduler,
        warmup_steps=max(1, math.ceil(train.warmup_ratio * total_steps)),
        num_train_epochs=train.epochs,
        max_steps=train.max_steps,
        logging_steps=train.logging_steps,
        eval_strategy="steps",
        eval_steps=train.eval_steps,
        save_strategy="steps",
        save_steps=train.eval_steps,
        save_total_limit=train.save_total_limit,
        restore_callback_states_from_checkpoint=True,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=True,
        optim=train.optimizer,
        gradient_checkpointing=train.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        report_to=["tensorboard"],
        seed=train.seed,
        data_seed=train.seed,
        dataloader_num_workers=0,
        remove_unused_columns=False,
        label_names=["labels"],
        prediction_loss_only=True,
        logging_nan_inf_filter=False,
        disable_tqdm=True,
        # پس از OOM واقعی با توالی‌های با طول متغیر، کش بلااستفاده‌ی CUDA بین گام‌ها آزاد می‌شود.
        torch_empty_cache_steps=1,
    )


def _progress_callback(total_steps: int, output_root: Path | None = None):
    from transformers import TrainerCallback

    class ProgressCallback(TrainerCallback):
        """گزارش پیشرفت فقط از مقادیر واقعی لاگ: گام، loss، eval_loss، زمان هر گام، پیک VRAM، زمان باقی‌مانده."""

        def __init__(self) -> None:
            self.started = time.perf_counter()
            self.initial_step = 0
            self.step_started = None
            self.step_seconds = []
            self.eval_seconds = []
            self.evaluation_records = 0

        def on_train_begin(self, args, state, control, **kwargs):
            self.initial_step = state.global_step
            self.started = time.perf_counter()

        def on_step_begin(self, args, state, control, **kwargs):
            if output_root is not None:
                check_resources(output_root)
            self.step_started = time.perf_counter()

        def on_substep_end(self, args, state, control, **kwargs):
            if output_root is not None:
                check_resources(output_root)

        def on_step_end(self, args, state, control, **kwargs):
            if self.step_started is not None:
                self.step_seconds.append(time.perf_counter() - self.step_started)

        def on_prediction_step(self, args, state, control, **kwargs):
            import torch

            if output_root is not None:
                check_resources(output_root)
            # روی GPU نمایشی ویندوز، کش انباشته نباید حاشیهٔ VRAM را در eval مصرف کند.
            torch.cuda.empty_cache()
            self.evaluation_records += 1
            if self.evaluation_records % 10 == 0:
                print(json.dumps({"evaluation_records": self.evaluation_records}), flush=True)

        def on_evaluate(self, args, state, control, metrics=None, **kwargs):
            if metrics and "eval_runtime" in metrics:
                self.eval_seconds.append(metrics["eval_runtime"])
            self.evaluation_records = 0

        def on_log(self, args, state, control, logs=None, **kwargs):
            import torch

            elapsed = time.perf_counter() - self.started
            step = max(state.global_step - self.initial_step, 1)
            line = {
                "step": state.global_step,
                "of": total_steps,
                "s_per_step": round(elapsed / step, 2),
                "eta_hours": round(elapsed / step * (total_steps - state.global_step) / 3600, 2),
                "vram_peak_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 2),
            }
            line.update({key: round(value, 4) for key, value in (logs or {}).items() if key in ("loss", "eval_loss")})
            print(json.dumps(line), flush=True)

    return ProgressCallback()


def _latest_checkpoint(directory: Path) -> str | None:
    checkpoints = sorted(
        (path for path in directory.glob("checkpoint-*") if path.is_dir() and path.name.split("-")[-1].isdigit()),
        key=lambda path: int(path.name.split("-")[-1]),
    )
    return str(checkpoints[-1]) if checkpoints else None


def prepare_run(config: RunConfig, resume: bool) -> str | None:
    """جلوگیری از بازنویسی اجرا یا ادامه با داده/پیکربندی متفاوت."""
    manifest_path = config.output_dir / "run_manifest.json"
    checkpoint = _latest_checkpoint(config.output_dir / CHECKPOINT_DIR)
    manifest = {
        "config": json.loads(json.dumps(asdict(config), default=str)),
        "dataset": dataset_fingerprint(config.data_dir),
    }
    if resume:
        if checkpoint is None or not manifest_path.exists():
            raise ValueError("checkpoint و مشخصات اجرای قابل ادامه پیدا نشد")
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        # نسخهٔ قبلی فقط مسیر native داشت؛ checkpointهای قبلی همچنان قابل ادامه‌اند.
        previous["config"]["train"].setdefault("kernel_backend", "native")
        if previous != manifest:
            raise ValueError("پیکربندی یا دیتاست با اجرای قبلی یکی نیست؛ run-id تازه انتخاب کنید")
    else:
        for path in (config.output_dir, config.logging_dir, config.report_dir):
            if path.exists() and any(path.iterdir()):
                raise ValueError("این run-id قبلاً استفاده شده؛ --resume یا run-id تازه لازم است")
        config.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return checkpoint


def tensorboard_session_origin(logging_dir: Path) -> Path:
    """نشانگر اولیه برای نسخه‌هایی که اولین START را آغاز جلسه و نه resume می‌دانند؛ بدون متریک ساختگی."""
    from tensorboard.compat.proto.event_pb2 import Event, SessionLog
    from tensorboard.summary.writer.event_file_writer import EventFileWriter

    root = logging_dir.resolve()
    marker = root / "events.out.tfevents.0000000000.resume-session-origin"
    if marker.exists():
        return marker
    staging = root / ".resume-origin-staging"
    staging.mkdir(parents=True, exist_ok=True)
    if any(staging.iterdir()):
        raise RuntimeError("پوشهٔ ساخت نشانگر resume خالی نیست؛ فایل قبلی بازنویسی نشد")
    writer = EventFileWriter(str(staging))
    try:
        writer.add_event(Event(wall_time=time.time(), step=0, session_log=SessionLog(status=SessionLog.START)))
    finally:
        writer.close()
    source = next(staging.glob("events.out.tfevents.*"))
    if not source.resolve().is_relative_to(root) or not marker.resolve().is_relative_to(root):
        raise RuntimeError("مسیر نشانگر باید در همان پوشهٔ رخدادها باشد")
    source.rename(marker)
    return marker


def resume_tensorboard_writer(trainer, checkpoint: str | None, logging_dir: Path):
    """نقاط بعد از checkpoint مخفی می‌شوند؛ فایل‌های رخداد قبلی حذف نمی‌شوند."""
    if checkpoint is None:
        return None
    from torch.utils.tensorboard import SummaryWriter
    from transformers.integrations import TensorBoardCallback

    tensorboard_session_origin(logging_dir)
    state = json.loads((Path(checkpoint) / "trainer_state.json").read_text(encoding="utf-8"))
    for callback in trainer.callback_handler.callbacks:
        if isinstance(callback, TensorBoardCallback):
            writer = SummaryWriter(log_dir=str(logging_dir), purge_step=state["global_step"] + 1)
            callback.tb_writer = writer
            return writer
    raise RuntimeError("callback ثبت زندهٔ TensorBoard برای ادامهٔ اجرا پیدا نشد")


def timing_report(config: RunConfig, progress, train_examples: int) -> dict:
    """برآورد اجرای کامل از زمان واقعی گام‌ها و اعتبارسنجی آزمایشی، بدون زمان دانلود."""
    if not progress.step_seconds:
        return {}
    step_seconds = median(progress.step_seconds[-10:])
    full_steps = math.ceil(train_examples / (config.train.batch_size * config.train.grad_accum)) * config.train.epochs
    result = {"optimizer_step_seconds_median": round(step_seconds, 3), "full_optimizer_steps": full_steps}
    if progress.eval_seconds:
        evaluation = median(progress.eval_seconds)
        validation_count = audited_records(config.data_dir)[1]["records"]["validation"]
        measured_count = min(config.train.eval_subset, validation_count)
        # سقف مبنا همان ۳۰۰ رکورد هر ۵۰ گام است؛ تنظیم کوچک smoke به برآورد اجرای کامل نشت نمی‌کند.
        intermediate = evaluation * min(300, validation_count) / measured_count
        final = evaluation * validation_count / measured_count
        estimate = (full_steps * step_seconds + (full_steps // 50) * intermediate + final) / 3600
        result.update(estimated_full_run_hours=round(estimate, 2), final_validation_seconds_estimate=round(final, 1))
    return result


def run(config: RunConfig, resume: bool) -> dict:
    print(json.dumps({"host_resources": check_resources(config.output_root, starting=True)}), flush=True)
    import os

    fast = config.train.kernel_backend == "liger_bf16"
    if fast:
        from training.lora.kernels import configure_liger

        configure_liger()
    import torch
    from transformers import EarlyStoppingCallback, Trainer, set_seed

    config.validate()
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("اجرای این پیکربندی به CUDA و bf16 نیاز دارد؛ gpu_check را اجرا کنید")
    if fast:
        # سهمی برای نمایشگر و تخصیص‌های خارج از allocator پایتورچ باقی می‌ماند.
        torch.cuda.set_per_process_memory_fraction(0.85, 0)
    set_seed(config.train.seed)
    # بررسی برخورد نام اجرا پیش از بارگذاری پرهزینه‌ی مدل؛ مشخصات فقط بعد از اعتبارسنجی داده ثبت می‌شود.
    tokenizer = load_tokenizer(config.base_model)
    splits, counts = load_splits(config, tokenizer)
    checkpoint = prepare_run(config, resume)
    os.environ["TENSORBOARD_LOGGING_DIR"] = str(config.logging_dir)
    torch.cuda.reset_peak_memory_stats()
    model = load_model(config)
    check_resources(config.output_root)
    if fast:
        from training.lora.kernels import cast_frozen_embeddings_to_bf16, patch_model

        patch_model(model)
        cast_frozen_embeddings_to_bf16(model)
    verify_target_modules(model, config.lora.target_modules)
    set_seed(config.train.seed)
    model = apply_lora(model, config.lora)
    model = discard_unused_training_logits(model, fused_loss=fast)
    total_steps = total_optimizer_steps(config, len(splits["train"].examples))
    progress = _progress_callback(total_steps, config.output_root)
    trainer = Trainer(
        model=model,
        args=training_arguments(config, total_steps),
        train_dataset=ListDataset(splits["train"].examples),
        eval_dataset=ListDataset(splits["eval_subset"].examples),
        data_collator=PadCollator(tokenizer.pad_token_id, answer_logits_only=config.train.answer_logits_only),
        callbacks=[EarlyStoppingCallback(config.train.early_stopping_patience), progress],
        processing_class=tokenizer,
    )
    print(f"TensorBoard: tensorboard --logdir {config.runs_root}  →  http://localhost:6006", flush=True)
    resume_writer = resume_tensorboard_writer(trainer, checkpoint, config.logging_dir)
    started = time.perf_counter()
    try:
        trainer.train(resume_from_checkpoint=checkpoint)
    except RuntimeError as error:
        if "out of memory" in str(error).lower():
            print(
                json.dumps(
                    {
                        "cuda_oom": True,
                        "allocated_gib": round(torch.cuda.memory_allocated() / 1024**3, 3),
                        "reserved_gib": round(torch.cuda.memory_reserved() / 1024**3, 3),
                        "peak_allocated_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
                    }
                ),
                flush=True,
            )
        raise
    finally:
        if resume_writer is not None:
            resume_writer.close()
    duration = time.perf_counter() - started
    timings = timing_report(config, progress, len(splits["train"].examples))
    print(json.dumps({"timing": timings}), flush=True)
    final_eval = {}
    if not config.train.smoke:
        final_eval = trainer.evaluate(
            ListDataset(splits["validation_full"].examples), metric_key_prefix="validation_full"
        )
    summary = export(config, trainer, tokenizer, counts, duration, final_eval, torch.cuda.max_memory_allocated())
    summary.update(
        timing=timings,
        resumed_from_step=progress.initial_step,
        torch_empty_cache_steps=1,
        discard_unused_training_logits=True,
        eval_empty_cache_per_batch=True,
        gpu_memory_fraction=0.85 if fast else None,
    )
    (config.report_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def export(config: RunConfig, trainer, tokenizer, counts: dict, duration: float, final_eval: dict, vram: int) -> dict:
    adapter_dir = config.output_dir / ADAPTER_DIR
    trainer.model.save_pretrained(adapter_dir, safe_serialization=False, save_embedding_layers=False)
    if any(not (adapter_dir / name).is_file() for name in ("adapter_config.json", "adapter_model.bin")):
        raise RuntimeError("فایل‌های خروجی آداپتر کامل نیستند")
    tokenizer.save_pretrained(adapter_dir)
    trainer.state.save_to_json(str(config.output_dir / "trainer_state.json"))
    summary = {
        "run_id": config.run_id,
        "run_kind": "smoke" if config.train.smoke else "training",
        "full_validation_completed": bool(final_eval),
        "config": json.loads(json.dumps(asdict(config), default=str)),
        "data": counts,
        "train_duration_hours": round(duration / 3600, 3),
        "global_steps": trainer.state.global_step,
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "best_eval_loss": trainer.state.best_metric,
        "validation_full": {key: round(value, 4) for key, value in final_eval.items() if isinstance(value, float)},
        "vram_peak_gb": round(vram / 1024**3, 2),
        "adapter_files_mb": {
            path.name: round(path.stat().st_size / 1024**2, 2) for path in sorted(adapter_dir.glob("adapter_*"))
        },
    }
    config.report_dir.mkdir(parents=True, exist_ok=True)
    (config.report_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = build_config(args)
    with keep_awake():
        run(config, args.resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
