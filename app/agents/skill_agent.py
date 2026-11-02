"""
عامل ۱ — استخراج مهارت (Skill Extraction Agent).

مهارت‌های متن رزومه را با گراف مهارت سیستم (app/core/skill_graph.py) تطبیق می‌دهد: نام استاندارد، مهارت اصلی
(گره والد)، دسته، تعداد دفعات ذکر مستقیم، استنتاجی بودن (Python از روی FastAPI) و میزان اطمینان. ادعای «N سال»
برای هر مهارت هم استخراج می‌شود تا عامل ناظر با سابقه‌ی واقعی مقایسه‌اش کند.

قطعی (Deterministic) و بدون شبکه: همان موتور مهارت خط لوله‌ی قبلی، با جزئیات بیشتر.
"""

from app.agents.schema import SkillAgentOutput, SkillItem
from app.agents.text_signals import extract_skill_year_claims
from app.core.skill_graph import count_skill_mentions

# اطمینان: ذکر مستقیم از ۰٫۶ شروع و با هر تکرار تا سقف ۱ بالا می‌رود؛ استنتاج فقط از زیرشاخه = ۰٫۵
_DIRECT_BASE_CONFIDENCE = 0.6
_PER_EXTRA_MENTION = 0.1
_INFERRED_CONFIDENCE = 0.5


def run_skill_agent(raw_text: str, parsed_data: dict | None, signals: dict | None = None) -> SkillAgentOutput:
    # یک پیمایش متن: مهارت‌های ذکرشده + تعدادشان؛ والد هر مهارت هم اضافه می‌شود — دقیقاً همان مجموعه‌ی
    # match_skills (و ستون skill_analysis خط لوله‌ی قبلی)
    mentions = count_skill_mentions(raw_text)
    claims = (signals or {}).get("skill_year_claims")
    if claims is None:
        claims = extract_skill_year_claims(raw_text)
    cores = {name: core for name, (core, _) in mentions.items()}
    for core in set(cores.values()):
        cores.setdefault(core, core)

    items: list[SkillItem] = []
    for name in sorted(cores):  # مرتب و قطعی
        core = cores[name]
        count = mentions.get(name, (core, 0))[1]
        if count:
            confidence = min(1.0, _DIRECT_BASE_CONFIDENCE + _PER_EXTRA_MENTION * (count - 1))
        else:
            confidence = _INFERRED_CONFIDENCE
        claim = claims.get(name)
        items.append(
            SkillItem(
                name=name,
                core=core,
                category=core,
                evidence_count=count,
                inferred=count == 0,
                confidence=round(confidence, 2),
                claimed_years=claim[0] if claim else None,
            )
        )
    return SkillAgentOutput(status="completed", skills=items)
