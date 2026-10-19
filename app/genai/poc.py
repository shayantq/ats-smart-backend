"""
اثبات مفهوم (PoC): یک رزومه‌ی نمونه + یک آگهی ← فهرست ساخت‌یافته‌ی سؤال‌های مصاحبه‌ی اختصاصی.

همان خط لوله‌ی واقعی برنامه، بدون دیتابیس:
    استخراج متن (PDF/DOCX/TXT) ← پارسر رزومه ← موتور مهارت ← نمره‌ی تطابق ← نقاط قوت/ضعف
        ← Prompt ← مدل زبانی (پروتکل Chat Completions) ← اعتبارسنجی با JSON Schema ← خروجی

    python -m app.genai.poc --resume docs/genai/samples/resume-backend.txt
        --job docs/genai/samples/job-senior-backend.json
    python -m app.genai.poc ... --count 6 --language fa --output result.json
    python -m app.genai.poc ... --dry-run          فقط پروفایل و Prompt (بدون فراخوانی مدل)

سرویس مدل از تنظیمات برنامه خوانده می‌شود (GENAI_BASE_URL، GENAI_MODEL، GENAI_API_KEY).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core.matching_engine import calculate_matching_score
from app.core.resume_parser import parse_resume_text
from app.core.skill_engine import run_skill_engine
from app.core.text_extraction import extract_raw_text
from app.genai.client import ChatCompletionsClient, GenAIError
from app.genai.prompts import PROMPT_VERSION, build_input_profile, build_messages
from app.genai.service import generate_questions


def read_resume_text(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8")
    return extract_raw_text(path.read_bytes(), path.name)


def build_profile_from_files(resume_path: Path, job: dict) -> dict:
    raw_text = read_resume_text(resume_path)
    parsed = parse_resume_text(raw_text).model_dump()
    analysis = run_skill_engine(raw_text, parsed.get("work_experience") or [])
    score = calculate_matching_score(
        job_skills_required=job.get("skills_required"),
        job_title=job.get("title") or "",
        job_required_seniority=job.get("required_seniority"),
        job_required_education=job.get("required_education"),
        job_location=job.get("location"),
        job_description=job.get("description"),
        candidate_skills=analysis.get("skills"),
        candidate_job_titles=[
            entry.get("job_title") for entry in parsed.get("work_experience") or [] if entry.get("job_title")
        ],
        candidate_total_experience_years=float(analysis.get("total_experience_years") or 0.0),
        candidate_education_entries=parsed.get("education"),
        candidate_location=None,
    )
    return build_input_profile(
        skill_analysis=analysis,
        parsed_data=parsed,
        raw_text=raw_text,
        self_declared_skills=None,
        match_score=round(score["final_score"]),
        job=job,
    )


def _print_summary(result, output: dict) -> None:
    completion = result.completion
    print(
        f"\n✔ {len(output['questions'])} سؤال ساخت‌یافته · {completion.latency_ms / 1000:.1f} ثانیه · "
        f"توکن ورودی/خروجی: {completion.prompt_tokens}/{completion.completion_tokens} · "
        f"اصلاح خروجی: {'بله' if result.repaired else 'خیر'} · Prompt: {PROMPT_VERSION}",
        file=sys.stderr,
    )
    for index, question in enumerate(output["questions"], start=1):
        print(
            f"  {index:>2}. [{question['category']}/{question['difficulty']}] {question['skill']}: "
            f"{question['question'][:110]}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.genai.poc", description=__doc__.split("\n")[1])
    parser.add_argument("--resume", required=True, type=Path, help="فایل رزومه: PDF، DOCX یا TXT")
    parser.add_argument("--job", required=True, type=Path, help="آگهی شغلی به‌صورت JSON")
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--difficulty", default="mixed", choices=["mixed", "easy", "medium", "hard"])
    parser.add_argument("--language", default="fa", choices=["fa", "en"])
    parser.add_argument("--focus", nargs="*", default=[], help="مهارت‌هایی که حتماً باید سنجیده شوند")
    parser.add_argument("--output", type=Path, help="ذخیره‌ی خروجی JSON در فایل")
    parser.add_argument("--dry-run", action="store_true", help="فقط پروفایل و Prompt، بدون فراخوانی مدل")
    args = parser.parse_args(argv)

    job = json.loads(args.job.read_text(encoding="utf-8"))
    profile = build_profile_from_files(args.resume, job)
    print("━━━ پروفایل ارسالی به مدل (بدون اطلاعات شخصی) ━━━", file=sys.stderr)
    print(json.dumps(profile["fit_analysis"], ensure_ascii=False, indent=2), file=sys.stderr)

    if args.dry_run:
        messages = build_messages(
            profile,
            question_count=args.count,
            difficulty=args.difficulty,
            focus_skills=args.focus,
            language=args.language,
        )
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        return 0

    try:
        with ChatCompletionsClient.from_settings() as client:
            result = generate_questions(
                profile,
                question_count=args.count,
                difficulty=args.difficulty,
                focus_skills=args.focus,
                language=args.language,
                client=client,
            )
    except GenAIError as error:
        print(f"✘ {error}", file=sys.stderr)
        return 1

    output = {
        "prompt_version": PROMPT_VERSION,
        "fit_analysis": profile["fit_analysis"],
        **result.question_set.model_dump(),
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    _print_summary(result, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
