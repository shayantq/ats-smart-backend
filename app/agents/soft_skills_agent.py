"""
عامل ۳ — تناسب فرهنگی و مهارت‌های نرم (Culture Fit & Soft Skills Agent).

بر پایه‌ی واژه‌نامه‌ی فارسی/انگلیسی (app/agents/data/soft_skills_lexicon.json — بدون تغییر کد قابل گسترش):
  - مهارت‌های نرم (ارتباط، رهبری، کار تیمی، مسئولیت‌پذیری، یادگیری، حل مسئله، انعطاف، مدیریت زمان) با امتیاز
    ۰ تا ۱ و عبارت‌های شاهد (خود عبارت واژه‌نامه، نه متن رزومه)
  - لحن نوشتار: تکرار نشانه‌های «قاطع/دستاوردمحور»، «جمعی»، «فردی» و «محتاط/مبهم» در هر ۱۰۰ کلمه، نسبت جمله‌های
    مجهول، و لحن غالب
  - میزان اطمینان تحلیل (متن کوتاه = اطمینان کم)

قطعی و بدون شبکه؛ تطبیق انگلیسی با مرز کلمه و فارسی با مرز حرف فارسی (تا «ما» داخل «ماه» شمرده نشود).
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from app.agents.schema import SoftSkillItem, SoftSkillsAgentOutput, ToneProfile

_LEXICON_PATH = Path(__file__).resolve().parent / "data" / "soft_skills_lexicon.json"
_FA_LETTERS = "؀-ۿ"
_HITS_FOR_FULL_SCORE = 3
_MAX_EVIDENCE = 3
_WORDS_FOR_FULL_CONFIDENCE = 300
_SENTENCE_SPLIT = re.compile(r"[.!?؟\n]+")
_WORD = re.compile(r"[\w‌]+")


def _group_pattern(phrases: list[str], persian: bool) -> re.Pattern | None:
    """
    همه‌ی عبارت‌های یک گروه در یک الگوی ترکیبی (یک پیمایش متن به‌جای یک پیمایش برای هر عبارت). عبارت بلندتر
    اول می‌آید تا «with the team» کامل گرفته شود و «team» داخلش دوبار شمرده نشود.
    """
    if not phrases:
        return None
    alternation = "|".join(re.escape(p) for p in sorted(set(phrases), key=len, reverse=True))
    if persian:
        return re.compile(rf"(?<![{_FA_LETTERS}])(?:{alternation})(?![{_FA_LETTERS}])")
    return re.compile(rf"(?<![a-z0-9])(?:{alternation})(?![a-z0-9])")


@lru_cache(maxsize=1)
def _lexicon() -> dict:
    """واژه‌نامه یک‌بار خوانده و الگوهایش کامپایل می‌شوند."""
    raw = json.loads(_LEXICON_PATH.read_text(encoding="utf-8"))

    def compile_group(group: dict) -> list[re.Pattern]:
        patterns = (_group_pattern(group.get("en", []), False), _group_pattern(group.get("fa", []), True))
        return [pattern for pattern in patterns if pattern is not None]

    return {
        "soft_skills": {
            key: {"label_fa": value["label_fa"], "patterns": compile_group(value)}
            for key, value in raw["soft_skills"].items()
        },
        "tone": {key: compile_group(value) for key, value in raw["tone"].items()},
        "passive_en": re.compile(raw["passive"]["en_pattern"], re.I),
        "passive_fa": _group_pattern(raw["passive"]["fa"], True),
    }


def _count(patterns: list[re.Pattern], text: str) -> tuple[int, list[str]]:
    """(تعداد کل، عبارت‌های یکتای دیده‌شده به ترتیب ظهور)"""
    found: list[str] = []
    for pattern in patterns:
        found.extend(pattern.findall(text))
    return len(found), list(dict.fromkeys(found))


def run_soft_skills_agent(
    raw_text: str, parsed_data: dict | None, signals: dict | None = None
) -> SoftSkillsAgentOutput:
    lexicon = _lexicon()
    text = (raw_text or "").lower()
    word_count = len(_WORD.findall(text))

    items: list[SoftSkillItem] = []
    total_hits = 0
    for key, entry in lexicon["soft_skills"].items():
        hits, phrases = _count(entry["patterns"], text)
        if hits:
            total_hits += hits
            items.append(
                SoftSkillItem(
                    key=key,
                    label_fa=entry["label_fa"],
                    score=round(min(1.0, hits / _HITS_FOR_FULL_SCORE), 2),
                    evidence=phrases[:_MAX_EVIDENCE],
                )
            )
    items.sort(key=lambda item: (-item.score, item.key))

    per_100 = 100 / word_count if word_count else 0.0
    tone_rates = {key: round(_count(patterns, text)[0] * per_100, 2) for key, patterns in lexicon["tone"].items()}
    sentences = [sentence for sentence in _SENTENCE_SPLIT.split(text) if sentence.strip()]
    passive = sum(
        1 for sentence in sentences if lexicon["passive_en"].search(sentence) or lexicon["passive_fa"].search(sentence)
    )
    dominant = max(tone_rates, key=tone_rates.get) if any(tone_rates.values()) else "neutral"
    tone = ToneProfile(
        **tone_rates,
        passive_voice_ratio=round(passive / len(sentences), 2) if sentences else 0.0,
        dominant=dominant,
    )

    confidence = min(1.0, word_count / _WORDS_FOR_FULL_CONFIDENCE) * (0.5 + 0.5 * min(1.0, total_hits / 5))
    return SoftSkillsAgentOutput(
        status="completed",
        soft_skills=items,
        tone=tone,
        word_count=word_count,
        confidence=round(confidence, 2),
    )
