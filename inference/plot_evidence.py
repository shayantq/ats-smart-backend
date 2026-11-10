"""ترسیم شواهد عددی واقعی؛ ابزار مستندسازی است و وارد کانتینر سرویس نمی‌شود."""

import argparse
import json
from pathlib import Path


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("training/reports/inference/gpu_baseline.json"))
    parser.add_argument("--output", type=Path, default=Path("training/reports/inference/gpu_evidence.png"))
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    for index, phase in enumerate(("sequential", "concurrent_2", "concurrent_4")):
        values = [row["seconds"] for row in report["rows"] if row["phase"] == phase and row["valid"]]
        axes[0].scatter([index] * len(values), values, s=22, alpha=0.7)
    axes[0].axhline(3, color="red", linestyle="--", label="Original target: <3 s")
    axes[0].set(xticks=range(3), xticklabels=["Sequential", "Concurrent 2", "Concurrent 4"], ylabel="Complete JSON (s)")
    axes[0].set_title("Real GPU container / 12 synthetic validation inputs")
    axes[0].legend(fontsize=8)
    memory = report["vram"]
    samples = [row for row in memory["samples"] if row["mib"] is not None]
    axes[1].plot([row["seconds"] for row in samples], [row["mib"] for row in samples], linewidth=1)
    axes[1].axvline(memory["warm_baseline_seconds"], color="gray", linestyle=":", label="Warm baseline")
    axes[1].axhline(
        memory["warm_baseline_mib"] + memory["tolerance_mib_declared_before_run"],
        color="orange",
        linestyle="--",
        label="Baseline +128 MiB tolerance",
    )
    axes[1].scatter([samples[-1]["seconds"] + 5], [memory["post_drain_mib"]], color="green", label="Post-drain")
    axes[1].set(xlabel="Elapsed (s)", ylabel="Whole GPU including desktop (MiB)")
    axes[1].set_title("Bounded soak; no engine restart")
    axes[1].legend(fontsize=8)
    for axis in axes:
        axis.grid(alpha=0.2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180)
    plt.close(figure)
    print(args.output)


if __name__ == "__main__":
    main()
