"""
پیکربندی آموزش تکمیلی LoRA — پایتون خالص (بدون torch) تا اعتبارسنجی‌اش در CI هم آزموده شود.

شناسه/مسیر مدل پایه هرگز در کد ثابت نمی‌شود: از پرچم --base-model، متغیر محیطی LORA_BASE_MODEL یا فایل
training/lora/model.env (در .gitignore؛ نمونه: model.env.example) خوانده می‌شود.
دلیل انتخاب هر مقدار پیش‌فرض: docs/finetune/LORA.md
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

BASE_MODEL_ENV = "LORA_BASE_MODEL"
MODEL_ENV_FILE = Path(__file__).with_name("model.env")
DEFAULT_TARGET_MODULES = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
VALID_BIAS = ("none", "all", "lora_only")


@dataclass(frozen=True)
class QuantSettings:
    """کوانتیزاسیون ۴ بیتی وزن‌های مدل پایه (QLoRA)."""

    quant_type: str = "nf4"
    double_quant: bool = True
    compute_dtype: str = "bfloat16"


@dataclass(frozen=True)
class LoraSettings:
    r: int = 16
    alpha: int = 32
    dropout: float = 0.05
    bias: str = "none"
    target_modules: tuple[str, ...] = DEFAULT_TARGET_MODULES

    def errors(self) -> list[str]:
        problems = []
        if self.r <= 0:
            problems.append("r باید مثبت باشد")
        if self.alpha <= 0:
            problems.append("lora_alpha باید مثبت باشد")
        if not 0 <= self.dropout < 1:
            problems.append("lora_dropout باید در بازه‌ی [0, 1) باشد")
        if not self.target_modules:
            problems.append("target_modules خالی است")
        if self.bias not in VALID_BIAS:
            problems.append(f"bias باید یکی از {VALID_BIAS} باشد")
        return problems


@dataclass(frozen=True)
class TrainSettings:
    max_seq_len: int = 2048
    batch_size: int = 1
    grad_accum: int = 16
    learning_rate: float = 2e-4
    scheduler: str = "cosine"
    warmup_ratio: float = 0.03
    epochs: int = 2
    eval_steps: int = 50
    eval_subset: int = 300
    early_stopping_patience: int = 3
    save_total_limit: int = 2
    logging_steps: int = 10
    optimizer: str = "paged_adamw_8bit"
    gradient_checkpointing: bool = True
    seed: int = 42
    max_steps: int = -1  # فقط برای اجرای آزمایشی (smoke run)؛ ‎-1 یعنی بر اساس epochs
    smoke: bool = False
    answer_logits_only: bool = True
    kernel_backend: str = "native"

    def errors(self) -> list[str]:
        positive = ("max_seq_len", "batch_size", "grad_accum", "eval_steps", "eval_subset", "logging_steps", "epochs")
        problems = [f"{name} باید مثبت باشد" for name in positive if getattr(self, name) <= 0]
        if self.learning_rate <= 0:
            problems.append("learning_rate باید مثبت باشد")
        if not 0 <= self.warmup_ratio < 1:
            problems.append("warmup_ratio باید در بازه‌ی [0, 1) باشد")
        if self.early_stopping_patience <= 0 or self.save_total_limit <= 0:
            problems.append("early_stopping_patience و save_total_limit باید مثبت باشند")
        if self.max_steps == 0 or self.max_steps < -1:
            problems.append("max_steps باید ‎-1 یا مثبت باشد")
        if self.smoke and self.max_steps <= 0:
            problems.append("اجرای آزمایشی باید تعداد گام محدود داشته باشد")
        if self.kernel_backend not in ("native", "liger_bf16"):
            problems.append("kernel_backend باید native یا liger_bf16 باشد")
        return problems


@dataclass(frozen=True)
class RunConfig:
    base_model: str
    run_id: str = "default"
    data_dir: Path = Path("data/finetune")
    output_root: Path = Path("training/outputs")
    runs_root: Path = Path("training/runs")
    reports_root: Path = Path("training/reports")
    quant: QuantSettings = field(default_factory=QuantSettings)
    lora: LoraSettings = field(default_factory=LoraSettings)
    train: TrainSettings = field(default_factory=TrainSettings)

    def validate(self) -> "RunConfig":
        problems = [] if self.base_model.strip() else ["مدل پایه مشخص نشده (--base-model یا LORA_BASE_MODEL)"]
        problems += self.lora.errors() + self.train.errors()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.run_id):
            problems.append("run_id باید نام ساده‌ی پوشه باشد، نه مسیر")
        if problems:
            raise ValueError("؛ ".join(problems))
        return self

    @property
    def output_dir(self) -> Path:
        return self.output_root / self.run_id

    @property
    def logging_dir(self) -> Path:
        return self.runs_root / self.run_id

    @property
    def report_dir(self) -> Path:
        return self.reports_root / self.run_id


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def resolve_base_model(cli_value: str | None) -> str:
    """اولویت: پرچم CLI ← متغیر محیطی ← training/lora/model.env."""
    return cli_value or os.environ.get(BASE_MODEL_ENV) or load_env_file(MODEL_ENV_FILE).get(BASE_MODEL_ENV, "")
