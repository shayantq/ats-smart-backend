"""
مقایسه‌ی زمان پردازش یک رزومه: خط لوله‌ی خطی قبلی در برابر اکوسیستم چندعاملی (app/agents).

    python loadtest/agent_benchmark.py              # ۲۴ رزومه‌ی نمونه × ۳ دور
    python loadtest/agent_benchmark.py --rounds 5

    # شرایط سرور: داخل ایمیج بک‌اند (Linux، Python 3.11، Tesseract و مدل NER همان Production) با ۲ هسته‌ی CPU
    # (deploy/agents-benchmark.sh همین را روی خود سرور اجرا می‌کند)

هر دو مسیر روی همان فایل خام اجرا می‌شوند و دقیقاً همان کار پردازشی را می‌کنند: استخراج متن + پارس + تحلیل +
نمره (بدون دیتابیس و صف، تا فقط زمان خود خط لوله سنجیده شود). هر دو مثل Worker واقعی داخل یک asyncio.run
اجرا می‌شوند (process_resume_task هر کار را در حلقه‌ی رویداد تازه اجرا می‌کند). رزومه‌ها در حافظه ساخته
می‌شوند، با تعداد متفاوت سابقه، مهارت و طول متن، در همان ترکیبی که به سامانه می‌رسد:
    ۸ PDF اسکن‌شده (فقط تصویر — OCR)، ۸ PDF متنی، ۴ DOCX انگلیسی، ۴ DOCX فارسی
نتیجه هم برای کل ترکیب و هم جدا برای هر نوع فایل گزارش می‌شود. ترتیب اجرای دو مسیر در
هر دور جابه‌جا می‌شود تا گرم بودن کش به نفع یکی نباشد.

معیار پذیرش: میانه و صدک ۹۵ زمان چندعاملی ≤ ۱٫۱۰ × خطی. خروج با کد ۱ اگر برقرار نباشد.
"""

import argparse
import asyncio
import io
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PII_ENCRYPTION_KEYS", "")  # این اسکریپت به دیتابیس و کلید نیازی ندارد

from docx import Document  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.agents.graph import run_agent_pipeline  # noqa: E402
from app.core.matching_engine import calculate_matching_score  # noqa: E402
from app.core.resume_parser import parse_resume_text  # noqa: E402
from app.core.skill_engine import run_skill_engine  # noqa: E402
from app.core.text_extraction import extract_raw_text  # noqa: E402

RATIO_LIMIT = 1.10
JOB = {
    "title": "Backend Developer",
    "skills_required": ["Python", "Docker", "PostgreSQL"],
    "required_seniority": "senior",
    "required_education": "bachelor",
    "location": "Tehran",
    "description": "FastAPI microservices on Kubernetes",
    "candidate_location": "Tehran",
}
SKILL_SETS = [
    "Python, Django, PostgreSQL, Docker",
    "Python (8 years), FastAPI, Redis, Kubernetes, AWS",
    "JavaScript, React, Node.js, MongoDB",
    "Java, Spring Boot, MySQL, Jenkins, Scrum",
    "C#, ASP.NET, SQL Server, Azure",
    "Python, Pandas, TensorFlow, Scikit-learn, GCP",
]
EN_SUMMARIES = [
    "Backend engineer with {years}+ years of experience. I led a small team, mentored juniors and we collaborated "
    "with stakeholders to deliver features on time.",
    "Developer focused on reliability. Responsible for end-to-end delivery, troubleshooting production issues and "
    "documentation. Familiar with agile teams.",
    "Software engineer who designed and built APIs, optimized slow queries and improved deployment pipelines. "
    "Self-taught, completed several certification courses.",
]
FA_SUMMARIES = [
    "توسعه‌دهنده‌ی بک‌اند با {years} سال سابقه. با همکاری تیم محصول، طراحی کردم و "
    "مستندسازی و رفع مشکل سیستم را انجام دادم.",
    "برنامه‌نویس با تجربه‌ی کار تیمی، مسئولیت‌پذیری و مدیریت زمان؛ علاقه به یادگیری و گواهینامه‌های تخصصی.",
    "کارشناس نرم‌افزار؛ سرپرستی تیم، بهینه‌سازی سرویس‌ها و تحویل به‌موقع پروژه‌ها.",
]


def _lines(index: int, persian: bool) -> list[str]:
    jobs = 1 + index % 4
    start = 2010 + index % 6
    years = 3 + index % 9
    summary = (FA_SUMMARIES if persian else EN_SUMMARIES)[index % 3].format(years=years)
    lines = [
        f"Candidate {index}",
        f"candidate{index}@example.test",
        "Summary",
        summary,
        "Skills",
        SKILL_SETS[index % 6],
    ]
    lines.append("Experience")
    for job in range(jobs):
        begin = start + job * 3
        lines += [
            ["Backend Developer", "Senior Engineer", "Tech Lead", "Software Developer"][job % 4],
            f"Company {index}-{job}",
            f"{begin} - {begin + 3 + (job % 2)}",
            ("پیاده‌سازی سرویس‌ها و همکاری با تیم. " if persian else "Built services and collaborated with the team. ")
            * (2 + index % 3),
        ]
    lines += ["Education", "B.Sc Computer Engineering", "University of Tehran"]
    return lines


def _docx(lines: list[str]) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf(lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    y = 800
    for line in lines:
        for chunk in [line[i : i + 95] for i in range(0, len(line), 95)] or [""]:
            page.drawString(40, y, chunk)
            y -= 14
            if y < 60:
                page.showPage()
                y = 800
    page.save()
    return buffer.getvalue()


def _scanned_pdf(lines: list[str]) -> bytes:
    """رزومه‌ی اسکن‌شده: صفحه‌ی A4 در ۱۵۰ DPI، فقط تصویر و بدون لایه‌ی متن — استخراج متن فقط با OCR."""
    width, height, margin = 1240, 1754, 70
    font = ImageFont.load_default(size=26)
    pages, page, y = [], None, height
    for line in lines:
        for chunk in [line[i : i + 70] for i in range(0, len(line), 70)] or [""]:
            if y > height - margin - 40:
                page = Image.new("L", (width, height), 255)
                pages.append(page)
                y = margin
            ImageDraw.Draw(page).text((margin, y), chunk, fill=0, font=font)
            y += 40
    buffer = io.BytesIO()
    pages[0].save(buffer, "PDF", resolution=150, save_all=True, append_images=pages[1:])
    return buffer.getvalue()


def build_fixtures() -> list[tuple[str, str, bytes]]:
    """(نوع، نام فایل، محتوا)"""
    fixtures = []
    for index in range(8):
        fixtures.append(("scanned-pdf", f"scan-{index}.pdf", _scanned_pdf(_lines(index + 60, persian=False))))
    for index in range(8):
        fixtures.append(("text-pdf", f"en-{index}.pdf", _pdf(_lines(index, persian=False))))
    for index in range(4):
        fixtures.append(("docx-en", f"en-{index}.docx", _docx(_lines(index + 20, persian=False))))
    for index in range(4):
        fixtures.append(("docx-fa", f"fa-{index}.docx", _docx(_lines(index + 40, persian=True))))
    return fixtures


async def _linear_async(file_bytes: bytes, filename: str) -> float:
    """همان مراحل خط لوله‌ی ترتیبی قبلی (app/tasks/resume_processing.py::_process_resume_linear)."""
    raw_text = extract_raw_text(file_bytes, filename=filename)
    parsed = parse_resume_text(raw_text).model_dump()
    analysis = run_skill_engine(raw_text, parsed.get("work_experience", []))
    result = calculate_matching_score(
        job_skills_required=JOB["skills_required"],
        job_title=JOB["title"],
        job_required_seniority=JOB["required_seniority"],
        job_required_education=JOB["required_education"],
        job_location=JOB["location"],
        job_description=JOB["description"],
        candidate_skills=analysis["skills"],
        candidate_job_titles=[e.get("job_title") for e in parsed.get("work_experience", []) if e.get("job_title")],
        candidate_total_experience_years=analysis["total_experience_years"],
        candidate_education_entries=parsed.get("education", []),
        candidate_location=JOB["candidate_location"],
    )
    return result["final_score"]


def run_linear(file_bytes: bytes, filename: str) -> float:
    return asyncio.run(_linear_async(file_bytes, filename))


def _usable_cpus() -> str:
    """تعداد هسته‌ی مجاز (سهمیه‌ی cgroup در Docker با --cpus، وگرنه تعداد هسته‌های سیستم)."""
    try:
        quota, period = open("/sys/fs/cgroup/cpu.max").read().split()
        if quota != "max":
            return f"{int(quota) / int(period):g} (سهمیه‌ی cgroup)"
    except (OSError, ValueError):
        pass
    return str(os.cpu_count())


def _percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(percent / 100 * (len(ordered) - 1)))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()

    fixtures = build_fixtures()
    # گرم کردن: بارگذاری مدل NER و موتور OCR، کامپایل واژه‌نامه و گراف — یک‌بار برای هر دو، خارج از اندازه‌گیری
    for kind in ("scanned-pdf", "text-pdf", "docx-fa"):
        _, name, data = next(fixture for fixture in fixtures if fixture[0] == kind)
        run_linear(data, name)
        asyncio.run(run_agent_pipeline(data, name, JOB))

    linear: dict[str, list[float]] = {}
    agents: dict[str, list[float]] = {}
    agent_phase_ms: list[float] = []
    overlapped = 0
    for round_index in range(args.rounds):
        for position, (kind, filename, data) in enumerate(fixtures):
            order = ("linear", "agents") if (round_index + position) % 2 == 0 else ("agents", "linear")
            for mode in order:
                started = time.perf_counter()
                if mode == "linear":
                    run_linear(data, filename)
                    linear.setdefault(kind, []).append((time.perf_counter() - started) * 1000)
                else:
                    analysis = asyncio.run(run_agent_pipeline(data, filename, JOB)).analysis
                    agents.setdefault(kind, []).append((time.perf_counter() - started) * 1000)
                    windows = [
                        analysis.timings_ms[n]
                        for n in ("skill_extraction", "experience_validation", "culture_fit_soft_skills")
                    ]
                    agent_phase_ms.append(max(w.end_ms for w in windows) - min(w.start_ms for w in windows))
                    overlapped += max(w.start_ms for w in windows) < min(w.end_ms for w in windows)

    def stats(values: list[float]) -> tuple[float, float, float]:
        return statistics.median(values), _percentile(values, 95), max(values)

    print(f"رزومه‌ها: {len(fixtures)} × {args.rounds} دور · CPU قابل‌استفاده: {_usable_cpus()}")
    print(f"{'نوع':<12} {'linear med/p95':>18} {'multi med/p95':>18} {'نسبت med/p95':>16}")
    for kind in [*linear, "ALL"]:
        lin = [v for values in linear.values() for v in values] if kind == "ALL" else linear[kind]
        agt = [v for values in agents.values() for v in values] if kind == "ALL" else agents[kind]
        (lm, lp, _), (am, ap, _) = stats(lin), stats(agt)
        print(f"{kind:<12} {lm:8.1f} /{lp:8.1f} {am:8.1f} /{ap:8.1f}   {am / lm:6.3f} / {ap / lp:6.3f}")
    all_linear = [v for values in linear.values() for v in values]
    all_agents = [v for values in agents.values() for v in values]
    median_ratio = statistics.median(all_agents) / statistics.median(all_linear)
    p95_ratio = _percentile(all_agents, 95) / _percentile(all_linear, 95)
    print(
        f"فاز عامل‌ها (هر سه): median={statistics.median(agent_phase_ms):.1f} ms · "
        f"p95={_percentile(agent_phase_ms, 95):.1f} ms"
    )
    print(f"هم‌پوشانی سه عامل: {overlapped}/{len(all_agents)} اجرا")
    print(f"نسبت کل ترکیب چندعاملی/خطی: median={median_ratio:.3f}   p95={p95_ratio:.3f}   (سقف {RATIO_LIMIT})")
    ok = median_ratio <= RATIO_LIMIT and p95_ratio <= RATIO_LIMIT
    print("[BENCHMARK PASS]" if ok else "[BENCHMARK FAIL]")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
