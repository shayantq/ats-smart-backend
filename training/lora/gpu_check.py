"""
بررسی محیط GPU پیش از آموزش:

    python -m training.lora.gpu_check

CUDA در دسترس، پشتیبانی bf16، و یک ضرب ماتریسی واقعی ۴ بیتی NF4 با bitsandbytes روی GPU (مقایسه با وزن
دی‌کوانتیزه‌شده). کد خروج ۱ اگر هر کدام برقرار نباشد.
"""

from __future__ import annotations

import json
import sys

MAX_4BIT_MATMUL_ERROR = 0.05
PROBE_FEATURES = 256


def _bnb_matmul_error(torch) -> float:
    import bitsandbytes as bnb

    layer = bnb.nn.Linear4bit(
        PROBE_FEATURES, PROBE_FEATURES, bias=False, compute_dtype=torch.bfloat16, quant_type="nf4"
    ).to("cuda")
    inputs = torch.randn(8, PROBE_FEATURES, dtype=torch.bfloat16, device="cuda")
    with torch.no_grad():
        output = layer(inputs)
        weight = bnb.functional.dequantize_4bit(layer.weight.data, layer.weight.quant_state).to(torch.bfloat16)
        reference = inputs @ weight.t()
    relative = (output.float() - reference.float()).abs().max() / reference.float().abs().max()
    return float(relative)


def main() -> int:
    import torch

    report = {"torch": torch.__version__, "cuda_available": torch.cuda.is_available()}
    if not report["cuda_available"]:
        print(json.dumps(report, indent=2))
        return 1
    properties = torch.cuda.get_device_properties(0)
    report.update(
        device=properties.name,
        cuda_runtime=torch.version.cuda,
        vram_gb=round(properties.total_memory / 1024**3, 2),
        bf16_supported=torch.cuda.is_bf16_supported(),
    )
    report["bnb_4bit_relative_error"] = round(_bnb_matmul_error(torch), 5)
    report["passed"] = report["bf16_supported"] and report["bnb_4bit_relative_error"] < MAX_4BIT_MATMUL_ERROR
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
