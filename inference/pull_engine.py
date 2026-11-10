"""دریافت محدود موتور با محافظ دیسک؛ فقط پردازهٔ دانلود همین اجرا کنترل می‌شود."""

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

GIB = 1024**3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=2700)
    parser.add_argument("--reserve-gib", type=int, default=30)
    parser.add_argument("--image", default="ollama/ollama:0.40.15")
    parser.add_argument("--report", type=Path, default=Path("training/reports/inference/ollama-pull-status.json"))
    args = parser.parse_args()
    if not 60 <= args.timeout <= 3600 or args.reserve_gib < 30:
        raise ValueError("مهلت یا حداقل فضای آزاد نامعتبر است")
    report = args.report
    if report.exists() and args.image != json.loads(report.read_text())["image"]:
        raise ValueError("گزارش به ایمیج دیگری تعلق دارد")
    report.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    status = {
        "image": args.image,
        "started_unix": time.time(),
        "reserve_gib": args.reserve_gib,
        "stop_threshold_gib": args.reserve_gib + 5,
        "timeout_seconds": args.timeout,
    }

    def save(state):
        status.update(state=state, seconds=time.monotonic() - started, free_bytes=shutil.disk_usage(".").free)
        report.write_text(json.dumps(status, indent=2), encoding="utf-8")

    save("preflight")
    if status["free_bytes"] < status["stop_threshold_gib"] * GIB:
        save("blocked_disk_budget")
        raise SystemExit(2)
    process = subprocess.Popen(["docker", "pull", status["image"]])
    state = "running"
    try:
        while process.poll() is None:
            save("running")
            if status["free_bytes"] < status["stop_threshold_gib"] * GIB:
                state = "stopped_disk_budget"
                break
            if time.monotonic() - started > args.timeout:
                state = "stopped_timeout"
                break
            time.sleep(2)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        status["exit_code"] = process.returncode
        save("completed" if process.returncode == 0 else state if state != "running" else "failed")
        with report.with_suffix(".events.jsonl").open("a", encoding="utf-8") as history:
            history.write(json.dumps(status) + "\n")
    raise SystemExit(0 if status["state"] == "completed" else 2)


if __name__ == "__main__":
    main()
