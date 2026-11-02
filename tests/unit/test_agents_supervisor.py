"""
تست واحد عامل «تناسب فرهنگی و مهارت‌های نرم»، عامل ناظر (قواعد حل تعارض، نمره، قرارداد JSON) و گراف چندعاملی
(اجرای موازی واقعی، شکست و تمام شدن زمان یک عامل).
"""

import asyncio
import io
import json
import time

import pytest
from docx import Document
from pydantic import ValidationError

from app.agents import graph as agent_graph
from app.agents import supervisor
from app.agents.experience_agent import run_experience_agent
from app.agents.schema import SCHEMA_VERSION, SoftSkillsAgentOutput, UnifiedAnalysis
from app.agents.skill_agent import run_skill_agent
from app.agents.soft_skills_agent import run_soft_skills_agent
from app.core.config import settings

JOB = {
    "title": "Backend Developer",
    "skills_required": ["Python", "Docker"],
    "required_seniority": "senior",
    "required_education": "bachelor",
    "location": "Tehran",
    "description": "FastAPI microservices",
    "candidate_location": "Tehran",
}
TIMINGS = {"supervisor_dispatch": {"start_ms": 0.0, "end_ms": 1.0, "duration_ms": 1.0}}


def _work(*rows):
    return {"work_experience": [{"company": c, "job_title": t, "duration": d} for c, t, d in rows], "education": []}


def _aggregate(text, parsed, job=JOB, soft=None, **overrides):
    payloads = {
        "skill_payload": run_skill_agent(text, parsed).model_dump(),
        "experience_payload": run_experience_agent(text, parsed).model_dump(),
        "soft_payload": soft if soft is not None else run_soft_skills_agent(text, parsed).model_dump(),
    }
    payloads.update(overrides)
    return supervisor.aggregate(parsed_data=parsed, job_context=job, timings=dict(TIMINGS), errors={}, **payloads)


# ---------------------------------------------------------------------------
# عامل مهارت نرم (واژه‌نامه‌ی فارسی و انگلیسی)
# ---------------------------------------------------------------------------
def test_english_soft_skills_and_tone():
    output = run_soft_skills_agent(
        "I led a team of five and mentored juniors. We collaborated with stakeholders and delivered on time.", None
    )
    skills = {item.key: item for item in output.soft_skills}

    assert {"leadership", "teamwork", "communication", "time_management", "ownership"} <= set(skills)
    assert "led" in skills["leadership"].evidence and "mentored" in skills["leadership"].evidence
    assert output.tone.dominant in {"collaborative", "confident"}
    assert all(0 <= item.score <= 1 for item in output.soft_skills)


def test_persian_soft_skills_without_false_substring_matches():
    output = run_soft_skills_agent("در ماه گذشته با همکاری تیم محصول، مستندسازی و رفع مشکل سیستم را انجام دادم.", None)
    skills = {item.key for item in output.soft_skills}

    assert {"teamwork", "communication", "problem_solving"} <= skills
    # «ما» داخل «ماه» و «من» داخل «منابع» شمرده نمی‌شوند
    individual = run_soft_skills_agent("منابع انسانی ماهانه", None).tone
    assert individual.individual == 0 and individual.collaborative == 0


def test_passive_voice_ratio():
    output = run_soft_skills_agent(
        "The system was designed by the team. Reports were generated. I built the API.", None
    )
    assert output.tone.passive_voice_ratio == pytest.approx(0.67, abs=0.01)


def test_short_text_has_low_confidence():
    assert run_soft_skills_agent("Python developer", None).confidence < 0.1
    assert run_soft_skills_agent("", None).soft_skills == []


# ---------------------------------------------------------------------------
# عامل ناظر: قواعد حل تعارض
# ---------------------------------------------------------------------------
def test_skill_years_above_validated_history_are_capped_and_recorded():
    analysis = _aggregate("Python (12 years)", _work(("A", "Developer", "2019 - 2023")))
    python = next(item for item in analysis.skills.items if item.name == "Python")
    conflict = next(c for c in analysis.conflicts_resolved if c.code == "skill_years_capped")

    assert python.claimed_years == 4.0 and python.confidence == pytest.approx(0.42)
    assert conflict.agents == ["skill_extraction", "experience_validation"]


def test_claimed_total_is_overridden_by_validated_periods():
    analysis = _aggregate("Developer with 15 years of experience", _work(("A", "Developer", "2019 - 2023")))
    assert any(c.code == "claimed_total_overridden" for c in analysis.conflicts_resolved)
    assert analysis.experience.total_experience_years == 4.0


def test_unsupported_leadership_is_halved():
    parsed = _work(("A", "Junior Developer", "2022 - 2023"))
    text = "I led the migration, led sprint planning and mentored interns."
    raw = run_soft_skills_agent(text, parsed)
    analysis = _aggregate(text, parsed)

    before = next(item.score for item in raw.soft_skills if item.key == "leadership")
    after = next(item.score for item in analysis.soft_skills.items if item.key == "leadership")
    assert after == pytest.approx(before / 2) and any(
        c.code == "leadership_unsupported" for c in analysis.conflicts_resolved
    )


def test_leadership_with_lead_title_is_kept():
    parsed = _work(("A", "Tech Lead", "2016 - 2023"))
    analysis = _aggregate("I led the team and mentored engineers.", parsed)
    assert not any(c.code == "leadership_unsupported" for c in analysis.conflicts_resolved)


def test_score_combines_base_engine_bonus_and_bounded_penalty():
    honest = _aggregate(
        "Python and Docker developer; we collaborated as a team.", _work(("A", "Backend Developer", "2016 - 2023"))
    )
    inflated = _aggregate(
        "Python and Docker developer with 25 years of experience, Python (20 years), Docker (20 years)",
        _work(
            ("A", "Senior Backend Developer", "2021 - 2023"), ("B", "Lead", "2021 - 2023"), ("C", "CTO", "2021 - 2023")
        ),
    )

    assert honest.matching.validation_penalty == 0 and honest.matching.soft_skill_bonus > 0
    assert honest.matching.score == pytest.approx(
        honest.matching.base_score + honest.matching.soft_skill_bonus, abs=0.02
    )
    assert inflated.matching.validation_penalty == supervisor.VALIDATION_MAX_PENALTY  # سقف جریمه
    assert inflated.matching.score < inflated.matching.base_score
    assert set(honest.matching.components) == {
        "skill_match",
        "title_match",
        "seniority_match",
        "education_match",
        "location_match",
        "secondary_keywords_match",
    }
    for analysis in (honest, inflated):
        assert 0 <= analysis.matching.score <= 100
        assert analysis.matching.soft_skill_bonus <= supervisor.SOFT_SKILL_MAX_BONUS


def test_without_job_context_there_is_no_score():
    analysis = _aggregate("Python", _work(("A", "Dev", "2020 - 2023")), job=None)
    assert analysis.matching.score is None and analysis.status == "completed"


def test_failed_agent_gives_partial_result_with_failed_section():
    analysis = _aggregate(
        "Python and Docker", _work(("A", "Dev", "2016 - 2023")), soft={"status": "failed", "error": "timeout>20s"}
    )

    assert analysis.status == "partial" and analysis.soft_skills.status == "failed"
    assert analysis.errors == {"culture_fit_soft_skills": "timeout>20s"}
    assert any(c.code == "agent_failed" for c in analysis.conflicts_resolved)
    assert analysis.matching.score is not None  # نمره با خروجی بقیه‌ی عامل‌ها


def test_unified_output_is_schema_valid_json_with_stable_types():
    analysis = _aggregate("Python (6 years), Docker. We delivered on time.", _work(("A", "Dev", "2016 - 2023")))
    payload = json.loads(analysis.model_dump_json())

    assert payload["schema_version"] == SCHEMA_VERSION
    assert set(payload) == {
        "schema_version",
        "status",
        "skills",
        "experience",
        "soft_skills",
        "conflicts_resolved",
        "flags",
        "matching",
        "errors",
        "timings_ms",
    }
    assert isinstance(payload["experience"]["total_experience_years"], float)
    assert UnifiedAnalysis.model_validate(payload) == analysis  # رفت‌وبرگشت بدون تغییر
    names = [item["name"] for item in payload["skills"]["items"]]
    assert len(names) == len(set(names))  # بدون مهارت تکراری


def test_schema_rejects_unknown_keys_and_type_drift():
    with pytest.raises(ValidationError):
        SoftSkillsAgentOutput.model_validate({"status": "completed", "unexpected": 1})
    with pytest.raises(ValidationError):
        SoftSkillsAgentOutput.model_validate({"status": "completed", "confidence": 2})


def test_skill_analysis_keeps_the_legacy_shape():
    analysis = _aggregate("FastAPI", _work(("A", "Dev", "2019 - 2023")))
    legacy = supervisor.to_skill_analysis(analysis)

    assert set(legacy) == {"skills", "total_experience_years", "experience_entries"}
    assert legacy["skills"] == ["FastAPI", "Python"] and legacy["total_experience_years"] == 4.0
    assert set(legacy["experience_entries"][0]) == {
        "company",
        "job_title",
        "duration",
        "start_year",
        "end_year",
        "is_valid",
        "flag_reason",
    }


# ---------------------------------------------------------------------------
# گراف: توزیع موازی واقعی، شکست و تمام شدن زمان یک عامل
# ---------------------------------------------------------------------------
def _docx(*lines) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


RESUME = _docx("Summary", "Python developer. We collaborated as a team.", "Skills", "Python, Docker")


def _slow(run, seconds):
    def wrapped(raw_text, parsed_data, signals=None):
        time.sleep(seconds)
        return run(raw_text, parsed_data, signals)

    return wrapped


@pytest.fixture
def slow_agents(monkeypatch):
    """هر عامل ۰٫۴ ثانیه طول می‌کشد؛ اجرای ترتیبی ≥ ۱٫۲ ثانیه، موازی ≈ ۰٫۴."""
    agent_graph.build_graph.cache_clear()
    monkeypatch.setattr(agent_graph, "run_skill_agent", _slow(run_skill_agent, 0.4))
    monkeypatch.setattr(agent_graph, "run_experience_agent", _slow(run_experience_agent, 0.4))
    monkeypatch.setattr(agent_graph, "run_soft_skills_agent", _slow(run_soft_skills_agent, 0.4))
    yield
    agent_graph.build_graph.cache_clear()


def test_supervisor_dispatches_the_three_agents_in_parallel(slow_agents):
    result = asyncio.run(agent_graph.run_agent_pipeline(RESUME, "cv.docx", JOB))
    timings = result.analysis.timings_ms
    windows = [timings[name] for name in supervisor.AGENTS]

    # هر سه بعد از توزیع شروع و پیش از جمع‌بندی تمام شده‌اند، و پنجره‌های اجرایشان هم‌پوشانی دارند
    assert all(window.start_ms >= timings["supervisor_dispatch"].end_ms for window in windows)
    assert all(window.end_ms <= timings["supervisor_aggregate"].start_ms for window in windows)
    assert max(window.start_ms for window in windows) < min(window.end_ms for window in windows)
    agents_phase = max(w.end_ms for w in windows) - min(w.start_ms for w in windows)
    assert agents_phase < 0.4 * 1000 * 2  # موازی: خیلی کمتر از ۱۲۰۰ میلی‌ثانیه‌ی ترتیبی
    assert result.analysis.status == "completed" and result.analysis.matching.score is not None


def test_a_crashing_agent_does_not_stop_the_pipeline(monkeypatch):
    agent_graph.build_graph.cache_clear()

    def broken(raw_text, parsed_data, signals=None):
        raise RuntimeError("sara@mail.test")  # پیام خطا ممکن است متن رزومه باشد — نباید به خروجی برسد

    monkeypatch.setattr(agent_graph, "run_experience_agent", broken)
    try:
        analysis = asyncio.run(agent_graph.run_agent_pipeline(RESUME, "cv.docx", JOB)).analysis
    finally:
        agent_graph.build_graph.cache_clear()

    assert analysis.status == "partial" and analysis.experience.status == "failed"
    assert analysis.errors["experience_validation"] == "RuntimeError"
    assert "sara@mail.test" not in analysis.model_dump_json()
    assert analysis.skills.status == "completed" and analysis.soft_skills.status == "completed"


def test_an_agent_over_its_time_budget_is_marked_failed(monkeypatch):
    agent_graph.build_graph.cache_clear()
    monkeypatch.setattr(settings, "AGENT_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(agent_graph, "run_soft_skills_agent", _slow(run_soft_skills_agent, 1.0))
    try:
        started = time.perf_counter()
        analysis = asyncio.run(agent_graph.run_agent_pipeline(RESUME, "cv.docx", JOB)).analysis
        elapsed = time.perf_counter() - started
    finally:
        agent_graph.build_graph.cache_clear()

    assert analysis.soft_skills.status == "failed" and analysis.errors["culture_fit_soft_skills"].startswith("timeout")
    assert analysis.status == "partial"
    assert elapsed < 5  # ناظر منتظر عامل کند نماند
