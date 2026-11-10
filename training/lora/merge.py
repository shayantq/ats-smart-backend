"""ادغام غیرکوانتیزهٔ لایه‌به‌لایه با PEFT؛ مناسب حافظهٔ محدود و بدون تغییر مبدأ."""

import argparse
import gc
import hashlib
import json
import shutil
from pathlib import Path

from training.lora.resources import GIB, windows_memory

REVISION = "aa8e72537993ba99e69dfaafa59ed015b17504d1"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def merge(base: Path, adapter: Path, output: Path, *, fp32_base: Path | None = None):
    import torch
    from peft import LoraConfig
    from peft.tuners.lora.layer import Linear
    from safetensors import safe_open
    from safetensors.torch import save_file

    if output.exists():
        raise FileExistsError("خروجی موجود است؛ بازنویسی مجاز نیست")
    if fp32_base is not None and fp32_base.exists():
        raise FileExistsError("خروجی پایهٔ FP32 موجود است")
    manifest = json.loads((base / "download_manifest.json").read_text(encoding="utf-8"))
    if manifest["revision"] != REVISION or not manifest.get("verified"):
        raise ValueError("نسخهٔ مدل پایه تأیید نشده است")
    for name, digest in manifest["sha256"].items():
        if sha256(base / name) != digest:
            raise ValueError("اثر انگشت وزن پایه نادرست است")
    memory = windows_memory()
    if memory and memory["commit_available"] < 3.5 * GIB:
        raise RuntimeError("برای ادغام لایه‌ای حداقل ۳٫۵ GiB حافظهٔ commit آزاد لازم است")
    if shutil.disk_usage(base).free < (26 if fp32_base else 9) * GIB:
        raise RuntimeError("فضای آزاد کافی نیست")
    config = json.loads((adapter / "adapter_config.json").read_text(encoding="utf-8"))
    if config["r"] != 16 or config["lora_alpha"] != 32 or config["bias"] != "none":
        raise ValueError("پیکربندی آداپتر با اجرای تأییدشده سازگار نیست")
    weights = torch.load(adapter / "adapter_model.bin", map_location="cpu", weights_only=True)
    index = json.loads((base / "model.safetensors.index.json").read_text(encoding="utf-8"))["weight_map"]
    output.mkdir(parents=True)
    if fp32_base:
        fp32_base.mkdir(parents=True)
    used, mapping, sizes = set(), {}, 0
    for number, (name, shard) in enumerate(sorted(index.items()), 1):
        with safe_open(base / shard, framework="pt", device="cpu") as handle:
            value = handle.get_tensor(name)
            if fp32_base:
                value = value.float()
                base_filename = f"model-{number:05d}-of-{len(index):05d}.safetensors"
                save_file({name: value}, fp32_base / base_filename, metadata={"format": "pt"})
            prefix = "base_model.model." + name.removesuffix(".weight")
            key_a, key_b = prefix + ".lora_A.weight", prefix + ".lora_B.weight"
            if key_a in weights:
                # محاسبهٔ delta و safe_merge در FP32؛ خروجی با dtype غیرکوانتیزهٔ مبدأ ذخیره می‌شود.
                linear = torch.nn.Linear(value.shape[1], value.shape[0], bias=False, device="meta")
                linear.weight = torch.nn.Parameter(value.float().clone(), requires_grad=False)
                layer = Linear(
                    linear,
                    "default",
                    config=LoraConfig(r=config["r"], lora_alpha=config["lora_alpha"], lora_dropout=0),
                    r=config["r"],
                    lora_alpha=config["lora_alpha"],
                )
                layer.lora_A.default.weight.data.copy_(weights[key_a])
                layer.lora_B.default.weight.data.copy_(weights[key_b])
                layer.merge(safe_merge=True)
                result = layer.base_layer.weight.detach().to(value.dtype).contiguous()
                used.update((key_a, key_b))
            else:
                result = value
            filename = f"model-{number:05d}-of-{len(index):05d}.safetensors"
            save_file({name: result}, output / filename, metadata={"format": "pt"})
            mapping[name] = filename
            sizes += result.numel() * result.element_size()
            del result, value
            if key_a in weights:
                del layer, linear
        if number % 50 == 0:
            print(json.dumps({"merged_tensors": number, "total": len(index)}), flush=True)
            gc.collect()
    if used != set(weights):
        raise ValueError("همهٔ وزن‌های آداپتر مصرف نشدند؛ خروجی ناقص قابل استفاده نیست")
    for name in (
        "config.json",
        "generation_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
    ):
        shutil.copyfile(base / name, output / name)
    (output / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {"total_size": sizes}, "weight_map": mapping}, indent=2), encoding="utf-8"
    )
    if fp32_base:
        for name in (
            "config.json",
            "generation_config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.json",
            "merges.txt",
            "model.safetensors.index.json",
        ):
            shutil.copyfile(output / name, fp32_base / name)
    report = {
        "base_revision": REVISION,
        "base_hashes_verified": True,
        "adapter_sha256": sha256(adapter / "adapter_model.bin"),
        "adapter_tensors_consumed": len(used),
        "output_tensors": len(mapping),
        "parameter_bytes": sizes,
        "method": "PEFT Linear.merge(safe_merge=True), FP32 delta",
        "storage_dtype": "float32" if fp32_base else "bfloat16",
        "behavior_verified": False,
    }
    (output / "merge_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path("models/base-model"))
    parser.add_argument("--adapter", type=Path, default=Path("training/outputs/ats-20261108-fast-01/adapter"))
    parser.add_argument("--output", type=Path, default=Path("models/ats-merged-bf16"))
    parser.add_argument("--fp32-base", type=Path, default=None)
    args = parser.parse_args()
    merge(args.base, args.adapter, args.output, fp32_base=args.fp32_base)


if __name__ == "__main__":
    main()
