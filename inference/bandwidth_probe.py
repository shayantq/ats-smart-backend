"""سنجش محدود copy حافظهٔ GPU؛ معادل سرعت مدل نیست و تنظیم توان تغییر نمی‌کند."""

import json
import subprocess
import time
from pathlib import Path

from training.lora.resources import GIB, windows_memory


def main():
    import torch

    report_path = Path("training/reports/inference/bandwidth_probe.json")
    if report_path.exists():
        raise FileExistsError("گزارش قبلی حفظ می‌شود")
    memory = windows_memory()
    tensor_bytes = GIB // 4
    iterations = 200
    if memory and memory["commit_available"] < 2.75 * GIB:
        raise MemoryError("ظرفیت commit برای آزمایش محدود کافی نیست")
    free, total = torch.cuda.mem_get_info()
    if free < 1.5 * GIB:
        raise MemoryError("GPU باید پیش از آزمایش آزاد باشد")
    x = torch.zeros(tensor_bytes, dtype=torch.uint8, device="cuda")
    y = torch.empty_like(x)
    for _ in range(5):
        y.copy_(x)
    torch.cuda.synchronize()
    rows = []
    for index in range(3):
        started = time.perf_counter()
        for _ in range(iterations):
            y.copy_(x)
        torch.cuda.synchronize()
        seconds = time.perf_counter() - started
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=clocks.sm,clocks.mem,power.draw,clocks_event_reasons.sw_power_cap,"
                "clocks_event_reasons.hw_thermal_slowdown",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        rows.append(
            {
                "repeat": index,
                "seconds": seconds,
                "copy_read_plus_write_gb_s": iterations * 2 * tensor_bytes / seconds / 1e9,
                "post_copy_device_state": query.stdout.strip(),
            }
        )
    report = {
        "gpu": torch.cuda.get_device_name(),
        "torch": torch.__version__,
        "total_vram_bytes": total,
        "copy_tensor_bytes": tensor_bytes,
        "copies_per_repeat": iterations,
        "rows": rows,
        "scope": "copy bandwidth only, not decode throughput or proof of a model roofline",
    }
    del x, y
    torch.cuda.empty_cache()
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
