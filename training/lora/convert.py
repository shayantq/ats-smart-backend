"""تبدیل و کوانتیزهٔ محدود با ابزار رسمی؛ مرحلهٔ جدا پس از برابری FP32."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from training.lora.merge import sha256
from training.lora.resources import GIB

CONVERTER_COMMIT = "547208dca250ceb3e4c8615598d043f2b602a527"
QUANTIZER_IMAGE = "ghcr.io/ggml-org/llama.cpp@sha256:4b7be0376002b4450a357a109bab804093ff9251193cc75ed4ce0cb39953ff5c"


def main():
    report_dir = Path("training/reports/inference")
    verification = json.loads((report_dir / "merge_fp32_verification.json").read_text(encoding="utf-8"))
    if not verification["passed"]:
        raise RuntimeError("برابری FP32 تأیید نشده است")
    source = Path("models/llama-converter")
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if commit != CONVERTER_COMMIT:
        raise ValueError("نسخهٔ مبدل تغییر کرده است")
    output = Path("models/ats-gguf").resolve()
    output.mkdir(parents=True, exist_ok=True)
    f16, q4 = output / "ats-f16.gguf", output / "ats-q4_k_m.gguf"
    if f16.exists() or q4.exists():
        raise FileExistsError("artifact قبلی بازنویسی نمی‌شود")
    if shutil.disk_usage(output).free < 10 * GIB:
        raise RuntimeError("فضای آزاد تبدیل کافی نیست")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path("models/converter-deps").resolve())
    environment["OMP_NUM_THREADS"] = "4"
    with (report_dir / "convert-f16.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            [
                sys.executable,
                str(source / "convert_hf_to_gguf.py"),
                "models/ats-merged-fp32",
                "--outtype",
                "f16",
                "--outfile",
                str(f16),
                "--use-temp-file",
            ],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=True,
        )
    print(json.dumps({"f16_bytes": f16.stat().st_size}), flush=True)
    with (report_dir / "quantize-q4.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--memory=1g",
                "--cpus=4",
                "--mount",
                f"type=bind,source={output},target=/data",
                "--entrypoint",
                "/app/llama",
                QUANTIZER_IMAGE,
                "quantize",
                "--max-buffer-size",
                "128",
                "/data/ats-f16.gguf",
                "/data/ats-q4_k_m.gguf",
                "Q4_K_M",
                "4",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=True,
        )
    report = {
        "source": "models/ats-merged-fp32",
        "merge_verification_passed": True,
        "converter_commit": CONVERTER_COMMIT,
        "quantizer_image": QUANTIZER_IMAGE,
        "files": {path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)} for path in (f16, q4)},
        "quality_verified": False,
    }
    (report_dir / "conversion.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
