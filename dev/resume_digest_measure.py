import json
import os
from pathlib import Path
from statistics import median, quantiles

from app.core.config import settings
from app.core.structured_resume import build_structured
from app.model_inference.budget import check_prompt_budget
from app.model_inference.resume_digest import ResumeDigestBuilder

RESUME_BUDGET = 1148
ROOT = Path(__file__).resolve().parents[1]


def sample_root() -> Path | None:
    directory = os.getenv("RESUME_SAMPLE_DIR")
    if not directory:
        return None
    root = Path(directory).resolve()
    if not root.is_dir() or root.is_relative_to(ROOT):
        raise ValueError("invalid_sample_directory")
    return root


def sample_file(root: Path, name: Path) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError("invalid_sample")
    return path


def synthetic_samples():
    english = (
        "Built reproducible synthetic data pipelines. "
        "Implemented staged quality checks with deterministic fixtures. " * 18
    ).strip()
    shared = (
        f"{english}\nDesigned modular transformations with transparent comparisons. "
        "Measured extraction consistency using generated examples."
    )
    persian = "مهندس داده | گروه آزمایشی\nتیر ۱۴۰۱ تا مهر ۱۴۰۲\n" + (
        "طراحی سامانه با داده‌های کاملاً ساختگی. اندازه‌گیری نتیجه با آزمون مستقل.\n" * 90
    )
    return [
        f"نمونه ساختگی\nسوابق کاری\n{persian}",
        (
            "Synthetic Example\nExperience\n"
            f"Software Engineer | Example Systems 01/2020 - 12/2021\n{shared}\n"
            f"Data Engineer | Fixture Labs 01/2022 - 12/2023\n{shared}\n"
            "Interests\n" + ("Independent study of generated demonstration data. " * 140)
        ),
        "مهارت‌ها\nC++ C# .NET Node.js\nزبان‌ها\nفارسی مادری",
    ]


def measure_sample(
    raw: str, layout: dict | None, structured: dict | None, tokenizer: str, *, token_budget: int = RESUME_BUDGET
) -> dict:
    def measure(text):
        return check_prompt_budget(text, token_budget, 0, tokenizer)

    raw_count = measure(raw)
    builder = ResumeDigestBuilder(
        raw,
        structured if structured is not None else build_structured(raw, layout),
        layout,
        icon_fonts=settings.RESUME_DIGEST_ICON_FONTS,
    )
    levels = []
    for level in range(3):
        digest = builder.build(level, measure, cap=settings.RESUME_DIGEST_DESCRIPTION_CAP)
        measured = digest.budget if digest else raw_count
        tokens = measured.prompt_tokens
        levels.append(
            dict(
                level=level,
                tokens=tokens,
                exact=int(measured.method == "exact"),
                cap_used=digest.cap_used if digest else None,
                digest_marker_collision=int(digest is None),
                reduction_pct=(
                    100 * (raw_count.prompt_tokens - tokens) / raw_count.prompt_tokens
                    if raw_count.prompt_tokens and raw_count.method == measured.method
                    else None
                ),
                retained_pct=digest.retained_pct if digest else 100,
                records_kept=len(digest.record_ids) if digest else len(builder.kept),
                omitted_by_record=list(digest.omitted_by_record.values()) if digest else [],
                unassigned_carried=digest.unassigned_carried if digest else builder.coverage["unassigned"],
                unassigned_omitted=digest.unassigned_omitted if digest else 0,
            )
        )
    return dict(
        raw_tokens=raw_count.prompt_tokens,
        raw_exact=int(raw_count.method == "exact"),
        raw_over_budget=raw_count.over_by,
        coverage=builder.coverage,
        levels=levels,
        exact_fit_levels=[row["level"] for row in levels if row["exact"] and row["tokens"] <= token_budget],
        estimated_fit_levels=[row["level"] for row in levels if not row["exact"] and row["tokens"] <= token_budget],
    )


def _distribution(values):
    values = list(value for value in values if value is not None)
    return {
        "n": len(values),
        "min": min(values, default=None),
        "median": median(values) if values else None,
        "max": max(values, default=None),
        "p95": quantiles(values, n=100, method="inclusive")[94] if len(values) >= 50 else None,
    }


def _sample_payload(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".txt":
        return text, None, None
    data = json.loads(text)
    return data["raw_text"], data.get("layout") or data.get("_extraction") or data, data.get("structured")


def main() -> int:
    try:
        token_budget = int(os.getenv("RESUME_DIGEST_MEASUREMENT_BUDGET", str(RESUME_BUDGET)))
        if token_budget <= 0:
            raise ValueError("invalid_measurement_budget")
        root = sample_root()
        candidates = sorted(root.iterdir()) if root else synthetic_samples()
    except Exception:
        print(json.dumps({"input_error": 1}))
        return 1
    local = ROOT / "models/base-model/tokenizer.json"
    tokenizer = settings.MODEL_INFERENCE_TOKENIZER_FILE or (str(local) if local.is_file() else "")
    rows = []
    invalid = unsupported = 0
    for index, sample in enumerate(candidates, 1):
        try:
            if root and sample.suffix.casefold() not in {".txt", ".json"}:
                unsupported += 1
                continue
            raw, layout, structured = _sample_payload(sample_file(root, sample)) if root else (sample, None, None)
            rows.append(dict(id=index, **measure_sample(raw, layout, structured, tokenizer, token_budget=token_budget)))
        except Exception:
            invalid += 1
    levels = [
        {
            "level": level,
            **{
                key: _distribution(row["levels"][level][key] for row in rows)
                for key in ("tokens", "reduction_pct", "retained_pct", "unassigned_carried", "unassigned_omitted")
            },
        }
        for level in range(3)
    ]
    print(
        json.dumps(
            dict(
                synthetic=int(root is None),
                resume_budget=token_budget,
                invalid=invalid,
                unsupported=unsupported,
                samples=rows,
                distributions=dict(
                    raw_tokens=_distribution(row["raw_tokens"] for row in rows),
                    coverage_pct=_distribution(row["coverage"]["coverage_pct"] for row in rows),
                    levels=levels,
                ),
            )
        )
    )
    return int(not rows)


if __name__ == "__main__":
    raise SystemExit(main())
