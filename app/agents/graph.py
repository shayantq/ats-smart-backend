"""
گراف اکوسیستم چندعاملی پردازش رزومه (LangGraph StateGraph):

                              ┌──► skill_extraction ─────────┐
    فایل خام ─► supervisor_dispatch ──► experience_validation ──► supervisor_aggregate ─► JSON یکپارچه
     (OCR + NER یک‌بار)       └──► culture_fit_soft_skills ──┘        (حل تعارض + نمره)

سه عامل در یک Superstep اجرا می‌شوند (Fan-out) و ناظر فقط بعد از تمام شدن هر سه (Fan-in) اجرا می‌شود. هر عامل در
Thread جدای یک Thread Pool ماندگار (ساخت Thread برای هر رزومه هزینه‌ی ثابت چندمیلی‌ثانیه‌ای داشت) و با سقف زمانی
AGENT_TIMEOUT_SECONDS اجرا می‌شود؛ شکست یا تمام شدن زمان یک عامل فقط بخش همان عامل را «failed» می‌کند و بقیه‌ی
گراف ادامه می‌دهد. خروجی عامل‌ها به‌صورت همان مدل‌های Pydantic در State می‌ماند (بدون تبدیل رفت‌وبرگشتی).

توجه: عامل‌ها کار CPU پایتونی‌اند؛ GIL اجازه‌ی اجرای واقعاً هم‌زمان روی چند هسته را نمی‌دهد. موازی بودن یعنی
هم‌پوشانی زمانی (و آمادگی برای عامل‌های I/O-محور مثل فراخوانی مدل زبانی)، نه چند برابر شدن سرعت. هزینه‌ی اصلی
(OCR و NER) فقط یک‌بار در dispatch پرداخت می‌شود، پس زمان کل از خط لوله‌ی خطی بیشتر نمی‌شود — بنگرید
loadtest/agent_benchmark.py.
"""

import asyncio
import operator
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache, partial
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents import supervisor
from app.agents.experience_agent import run_experience_agent
from app.agents.schema import Timing, UnifiedAnalysis
from app.agents.skill_agent import run_skill_agent
from app.agents.soft_skills_agent import run_soft_skills_agent
from app.agents.text_signals import compute_shared_signals
from app.core.config import settings


# ماندگار در طول عمر پردازه‌ی Worker (هر کار با asyncio.run حلقه‌ی تازه می‌سازد، ولی Thread ها همین‌ها هستند).
# ظرفیت بیش از سه عامل: Thread عاملی که زمانش تمام شده تا پایان کارش اشغال می‌ماند (Thread قابل کشتن نیست)
_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="resume-agent")


class PipelineState(TypedDict, total=False):
    file_bytes: bytes
    filename: str
    job_context: dict | None
    started_at: float
    raw_text: str
    parsed_data: dict | None
    signals: dict  # سیگنال‌های متنی مشترک چند عامل — یک‌بار در توزیع (app/agents/text_signals.py)
    skill_extraction: Any  # خروجی مدل Pydantic عامل، یا {"status": "failed", "error": ...}
    experience_validation: Any
    culture_fit_soft_skills: Any
    # Reducer: هر عامل موازی کلید خودش را اضافه می‌کند؛ ادغام بدون تداخل
    timings: Annotated[dict, operator.or_]
    errors: Annotated[dict, operator.or_]
    analysis: UnifiedAnalysis


def _elapsed_ms(state: PipelineState) -> float:
    return round((time.perf_counter() - state["started_at"]) * 1000, 2)


def _timing(start: float, end: float) -> dict:
    return Timing(start_ms=start, end_ms=end, duration_ms=round(end - start, 2)).model_dump()


async def _dispatch(state: PipelineState) -> dict:
    start = _elapsed_ms(state)
    # مستقیم و بدون Thread: در این لحظه کار دیگری در این حلقه نیست (Worker هر رزومه را در حلقه‌ی خودش اجرا می‌کند).
    # خطای استخراج متن (فایل ناخوانا/خراب) بالا می‌رود: بدون متن هیچ عاملی معنا ندارد (همان رفتار خط لوله‌ی خطی)
    raw_text, parsed_data, parse_error = supervisor.dispatch(state["file_bytes"], state["filename"])
    update: dict[str, Any] = {
        "raw_text": raw_text,
        "parsed_data": parsed_data,
        "signals": compute_shared_signals(raw_text),
        "timings": {"supervisor_dispatch": _timing(start, _elapsed_ms(state))},
    }
    if parse_error:
        update["errors"] = {"parser": parse_error}
    return update


def _agent_node(name: str, run: Callable) -> Callable:
    async def node(state: PipelineState) -> dict:
        start = _elapsed_ms(state)
        error = None
        try:
            loop = asyncio.get_running_loop()
            payload = await asyncio.wait_for(
                loop.run_in_executor(
                    _AGENT_EXECUTOR, partial(run, state["raw_text"], state.get("parsed_data"), state.get("signals"))
                ),
                timeout=settings.AGENT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            error = f"timeout>{settings.AGENT_TIMEOUT_SECONDS:g}s"
        except Exception as exc:  # noqa: BLE001 - شکست یک عامل نباید کل گراف را متوقف کند
            # فقط نوع خطا (پیام ممکن است تکه‌ای از متن رزومه داشته باشد)
            error = type(exc).__name__
        if error:
            payload = {"status": "failed", "error": error}
        update = {name: payload, "timings": {name: _timing(start, _elapsed_ms(state))}}
        if error:
            update["errors"] = {name: error}
        return update

    node.__name__ = name
    return node


async def _aggregate(state: PipelineState) -> dict:
    start = _elapsed_ms(state)
    errors = {key: value for key, value in state.get("errors", {}).items() if key != "parser"}
    timings = dict(state.get("timings", {}))
    analysis = supervisor.aggregate(
        skill_payload=state.get(supervisor.SKILL_AGENT),
        experience_payload=state.get(supervisor.EXPERIENCE_AGENT),
        soft_payload=state.get(supervisor.SOFT_SKILLS_AGENT),
        parsed_data=state.get("parsed_data"),
        job_context=state.get("job_context"),
        timings={**timings, "supervisor_aggregate": _timing(start, start)},
        errors=errors,
    )
    end = _elapsed_ms(state)
    analysis.timings_ms["supervisor_aggregate"] = Timing(start_ms=start, end_ms=end, duration_ms=round(end - start, 2))
    return {"analysis": analysis}


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("supervisor_dispatch", _dispatch)
    for name, run in (
        (supervisor.SKILL_AGENT, run_skill_agent),
        (supervisor.EXPERIENCE_AGENT, run_experience_agent),
        (supervisor.SOFT_SKILLS_AGENT, run_soft_skills_agent),
    ):
        graph.add_node(name, _agent_node(name, run))
        graph.add_edge("supervisor_dispatch", name)
    graph.add_node("supervisor_aggregate", _aggregate)
    graph.add_edge(list(supervisor.AGENTS), "supervisor_aggregate")  # Fan-in: منتظر هر سه
    graph.add_edge(START, "supervisor_dispatch")
    graph.add_edge("supervisor_aggregate", END)
    return graph.compile()


@dataclass
class PipelineResult:
    raw_text: str
    parsed_data: dict | None
    analysis: UnifiedAnalysis


async def run_agent_pipeline(file_bytes: bytes, filename: str, job_context: dict | None) -> PipelineResult:
    """فایل خام رزومه ← عامل ناظر ← سه عامل موازی ← JSON یکپارچه (اعتبارسنجی‌شده با UnifiedAnalysis)."""
    started_at = time.perf_counter()
    state = await build_graph().ainvoke(
        {"file_bytes": file_bytes, "filename": filename, "job_context": job_context, "started_at": started_at}
    )
    analysis = state["analysis"]  # همان مدل اعتبارسنجی‌شده‌ی ناظر
    total = round((time.perf_counter() - started_at) * 1000, 2)
    analysis.timings_ms["total"] = Timing(start_ms=0.0, end_ms=total, duration_ms=total)
    return PipelineResult(raw_text=state["raw_text"], parsed_data=state.get("parsed_data"), analysis=analysis)
