"""کرنل‌های اختیاری آزمایشی؛ محیط پایه و هایپرپارامترهای آموزش را تغییر نمی‌دهند."""

from __future__ import annotations

import json
import os
import sys
from functools import wraps
from pathlib import Path


def configure_liger() -> None:
    dependency_dir = Path(__file__).resolve().parents[1] / "reports" / "kernel-deps"
    if not (dependency_dir / "triton").is_dir() or not (dependency_dir / "liger_kernel").is_dir():
        raise RuntimeError("وابستگی کرنل آزمایشی در پوشهٔ جدا نصب نشده است")
    sys.path.insert(0, str(dependency_dir))
    # تغییر فقط برای پردازهٔ جاری است؛ PATH و پکیج‌های سیستم دست‌نخورده می‌مانند.
    os.environ["CUDA_PATH"] = str(dependency_dir / "triton" / "backends" / "nvidia")
    os.environ["TRITON_CACHE_DIR"] = str(dependency_dir.parent / "triton-cache")
    compiler = dependency_dir / "triton" / "runtime" / "tcc" / "tcc.exe"
    if os.name == "nt" and compiler.is_file():
        os.environ["CC"] = str(compiler)


def patch_model(model) -> None:
    from liger_kernel.transformers import apply_liger_kernel_to_qwen2
    from liger_kernel.transformers.model import qwen2

    if model.config.model_type != "qwen2":
        raise ValueError("کرنل این آزمایش فقط برای معماری بررسی‌شدهٔ مدل فعلی فعال است")
    original_loss = qwen2.LigerForCausalLMLoss
    if not getattr(original_loss, "_compact_response_rows", False):

        @wraps(original_loss)
        def response_loss(*args, **kwargs):
            hidden = kwargs.get("hidden_states")
            labels = kwargs.get("shift_labels")
            if labels is not None and hidden is not None and hidden.shape[:2] == labels.shape:
                # متن کامل در Transformer می‌ماند؛ فقط ردیف‌های پاسخ وارد projection واژگان می‌شوند.
                valid = labels != kwargs.get("ignore_index", -100)
                kwargs.update(
                    hidden_states=hidden[valid].unsqueeze(0), shift_labels=labels[valid].unsqueeze(0), labels=None
                )
            return original_loss(*args, **kwargs)

        response_loss._compact_response_rows = True
        qwen2.LigerForCausalLMLoss = response_loss
    apply_liger_kernel_to_qwen2(model=model)


def cast_frozen_embeddings_to_bf16(model) -> dict:
    """بازگرداندن embedding منجمد به bf16، فقط اگر مقدار تک‌تک وزن‌ها دقیقاً حفظ شود."""
    import torch

    modules = [model.get_input_embeddings(), model.get_output_embeddings()]
    checked = set()
    for module in modules:
        if module is None or id(module.weight) in checked:
            continue
        checked.add(id(module.weight))
        if any(parameter.requires_grad for parameter in module.parameters()):
            raise ValueError("تبدیل dtype فقط برای embedding کاملاً منجمد مجاز است")
        # بررسی قطعه‌ای، بدون کپی بزرگ واژگان در VRAM یا RAM.
        with torch.no_grad():
            for chunk in module.weight.split(4096):
                if not torch.equal(chunk, chunk.to(torch.bfloat16).to(chunk.dtype)):
                    raise ValueError("تبدیل dtype مقدار وزن پایه را تغییر می‌دهد؛ گزینه رد شد")
    for module in modules:
        if module is not None:
            module.to(dtype=torch.bfloat16)
    if model.config.tie_word_embeddings:
        model.tie_weights()
    return {"dtype": "bfloat16", "frozen_weight_values_preserved": True}


def check_equivalence(*, bf16_embeddings: bool = False) -> dict:
    """مقایسهٔ loss و گرادیان همهٔ آداپترها روی مدل کوچک واقعی NF4؛ بدون دادهٔ test."""
    configure_liger()
    import tempfile
    import torch
    from transformers import Qwen2Config, Qwen2ForCausalLM
    from training.lora.config import LoraSettings, RunConfig
    from training.lora.data import PadCollator
    from training.lora.train import apply_lora, discard_unused_training_logits, load_model

    root = Path("training/outputs").resolve()
    root.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(73)
    with tempfile.TemporaryDirectory(prefix="kernel-fixture-", dir=root) as directory:
        if not Path(directory).resolve().is_relative_to(root):
            raise RuntimeError("مسیر fixture باید داخل پوشهٔ خروجی باشد")
        fixture = Qwen2ForCausalLM(
            Qwen2Config(
                vocab_size=256,
                hidden_size=64,
                intermediate_size=128,
                num_hidden_layers=2,
                num_attention_heads=4,
                num_key_value_heads=2,
                max_position_embeddings=64,
            )
        )
        fixture.save_pretrained(directory)
        del fixture
        model = apply_lora(load_model(RunConfig(base_model=directory)), LoraSettings(dropout=0))
    model.train()
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            if "lora_B" in name:
                parameter.normal_(std=0.01)
    features = [
        {"input_ids": list(range(1, 25)), "labels": [-100] * 12 + list(range(13, 25))},
        {"input_ids": list(range(25, 43)), "labels": [-100] * 7 + list(range(32, 43))},
    ]
    batch = {key: value.cuda() for key, value in PadCollator(0, answer_logits_only=True)(features).items()}
    normalizers = [None, torch.tensor(64, device="cuda")]
    references = []
    for normalizer in normalizers:
        extra = {} if normalizer is None else {"num_items_in_batch": normalizer}
        model.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            loss = model(**batch, **extra).loss
        loss.backward()
        references.append(
            (
                loss.detach().float().cpu(),
                {
                    name: parameter.grad.detach().float().cpu().clone()
                    for name, parameter in model.named_parameters()
                    if parameter.requires_grad
                },
            )
        )
    patch_model(model.get_base_model())
    if bf16_embeddings:
        cast_frozen_embeddings_to_bf16(model.get_base_model())
    model = discard_unused_training_logits(model, fused_loss=True)
    loss_errors, gradient_errors = [], []
    for normalizer, (reference_loss, gradients) in zip(normalizers, references):
        extra = {} if normalizer is None else {"num_items_in_batch": normalizer}
        model.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            loss = model(**batch, **extra)["loss"]
        loss.backward()
        torch.testing.assert_close(loss.float().cpu(), reference_loss, atol=0.003, rtol=0.001)
        loss_errors.append(abs(float(loss.detach()) - float(reference_loss)))
        for name, parameter in model.named_parameters():
            if parameter.requires_grad:
                gradient = parameter.grad.detach().float().cpu()
                reference = gradients[name]
                relative = float((gradient - reference).norm() / reference.norm().clamp_min(1e-8))
                gradient_errors.append(relative)
                if not torch.isfinite(gradient).all() or relative > 0.03:
                    raise RuntimeError("گرادیان کرنل اختیاری با مرجع bf16 سازگار نیست")
    report = {
        "passed": True,
        "quantization": "nf4_double_quant",
        "compute_dtype": "bfloat16",
        "loss_absolute_errors": loss_errors,
        "max_gradient_relative_l2": max(gradient_errors),
        "gradient_relative_l2_limit": 0.03,
        "normalization_modes_checked": 2,
        "adapter_gradients_checked": len(gradient_errors),
        "heldout_test_used": False,
        "embedding_dtype": "bfloat16" if bf16_embeddings else "float32",
        "response_rows_compacted": True,
    }
    name = "kernel-equivalence-bf16.json" if bf16_embeddings else "kernel-equivalence.json"
    path = Path("training/reports") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bf16-embeddings", action="store_true")
    check_equivalence(bf16_embeddings=parser.parse_args().bf16_embeddings)
