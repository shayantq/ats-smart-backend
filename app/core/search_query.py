"""
ابزار تبدیل عبارت جستجوی متنی آزاد کاربر (که می‌تواند شامل عملگرهای منطقی
AND/OR باشد، مثلاً "Python AND Django" یا "React OR Vue") به یک عبارت معتبر
برای ورودی تابع to_tsquery پستگرس (بنگرید app/routers/candidates.py، موتور
جستجوی پیشرفته‌ی رزومه‌ها).

چرا websearch_to_tsquery پستگرس استفاده نشده؟
------------------------------------------------
websearch_to_tsquery کلیدواژه‌ی "or" را به‌عنوان عملگر OR می‌شناسد، ولی
"and" را یک کلمه‌ی عادی جستجو در نظر می‌گیرد (چون Postgres پیکربندی 'simple'
هیچ Stopword‌ای حذف نمی‌کند — دقیقاً همان پیکربندی‌ای که ایندکس GIN رزومه‌ها
با آن ساخته شده، بنگرید مایگریشن 852de21930b5). یعنی "Python AND Django" با
websearch_to_tsquery تبدیل می‌شد به جستجوی سه کلمه‌ی "python"، "and" و
"django" با هم (AND ضمنی پیش‌فرض) — دقیقاً برعکسِ رفتاری که معیار پذیرش تسک
می‌خواهد. به همین دلیل این پارسر دستی نوشته شده تا هم AND و هم OR را صریح و
Case-Insensitive تشخیص دهد.
"""

from __future__ import annotations

import re

from sqlalchemy import func, literal_column
from sqlalchemy.sql.elements import ColumnElement


# جداکننده‌ی عملگرهای منطقی: با فاصله از دو طرف احاطه شده باشند تا کلماتی
# مثل "Andrew" یا "Orlando" به اشتباه عملگر تشخیص داده نشوند.
_OPERATOR_SPLIT_PATTERN = re.compile(r"\s+(AND|OR)\s+", re.IGNORECASE)

# هر کلمه فقط از حروف (فارسی/انگلیسی) و اعداد تشکیل می‌شود؛ هر کاراکتر دیگر
# (مثل '، "، ؛، --، و ...) پیش از رسیدن به to_tsquery حذف می‌شود تا امکان
# بروز خطای Syntax در تجزیه‌گر tsquery پستگرس وجود نداشته باشد.
_WORD_PATTERN = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)


def build_resume_search_tsquery(raw_query: str | None) -> str | None:
    """
    ورودی: عبارت خام جستجوی کاربر (پارامتر q).
    خروجی: یک رشته‌ی آماده برای func.to_tsquery('simple', <خروجی>)، یا None
    اگر بعد از پاک‌سازی هیچ کلمه‌ی معتبری باقی نماند (مثلاً ورودی فقط شامل
    نویسه‌های خاص بود).

    قوانین:
    - AND/OR به‌صورت Case-Insensitive شناسایی می‌شوند (طبق معیار پذیرش تسک).
    - بین دو عبارت متوالیِ بدون عملگر صریح (فقط با فاصله جدا شده)، AND
      پیش‌فرض در نظر گرفته می‌شود — دقیقاً همان رفتاری که کاربر از یک
      جستجوی چندکلمه‌ای معمولی انتظار دارد.
    - عبارت نهایی، عبارت‌های متوالی را از چپ به راست و به‌ترتیب با پرانتزبندی
      صریح ترکیب می‌کند (بدون اولویت ضمنی بین AND/OR) تا رفتار همیشه قابل‌پیش‌بینی
      و قطعی باشد.
    """
    if not raw_query:
        return None

    raw_query = raw_query.strip()
    if not raw_query:
        return None

    segments = _OPERATOR_SPLIT_PATTERN.split(raw_query)

    combined_expr: str | None = None
    pending_operator = "&"  # پیش‌فرض بین دو عبارت متوالی بدون عملگر صریح: AND

    for index, segment in enumerate(segments):
        # segments همیشه به‌صورت متناوب [عبارت, عملگر, عبارت, عملگر, ...] است
        if index % 2 == 1:
            pending_operator = "|" if segment.upper() == "OR" else "&"
            continue

        words = _WORD_PATTERN.findall(segment)
        if not words:
            continue

        term_expr = " & ".join(words)
        if len(words) > 1:
            term_expr = f"({term_expr})"

        combined_expr = term_expr if combined_expr is None else f"({combined_expr} {pending_operator} {term_expr})"

    return combined_expr


# نویسه‌هایی که پیش از to_tsvector به فاصله تبدیل می‌شوند (بنگرید توضیح تابع
# resume_fts_tsvector_expression پایین همین فایل).
_FTS_PUNCTUATION_CHARS = "./+#@_-"
_FTS_PUNCTUATION_REPLACEMENT = " " * len(_FTS_PUNCTUATION_CHARS)


def resume_fts_tsvector_expression(raw_text_column: ColumnElement) -> ColumnElement:
    """
    عبارت to_tsvector مشترکی که هم در کوئری جستجو (app/routers/candidates.py)
    و هم در تعریف ایندکس GIN (مایگریشن مربوطه — بنگرید پایین) استفاده می‌شود؛
    این دو باید همیشه دقیقاً یکی باشند وگرنه پستگرس نمی‌تواند از ایندکس
    استفاده کند.

    ⚠️ باگ کشف‌شده و رفع‌شده (نسخه‌ی اول این تابع این کار را نمی‌کرد):
    پارسر پیش‌فرض متن پستگرس، رشته‌هایی مثل "Node.js" یا "C++" را طبق قواعد
    توکنایزیشن خودش (تشخیص الگوی «شبه‌میزبان»/«شبه‌فایل» برای کلمه.کلمه) یک
    توکن واحد "node.js" می‌بیند، نه دو کلمه‌ی جدای "node" و "js" — یعنی جستجوی
    تک‌کلمه‌ای "Node" هیچ‌وقت با رزومه‌ای که فقط "Node.js" نوشته مطابقت پیدا
    نمی‌کرد (دقیقاً چیزی که باعث خالی برگشتن نتایج جستجوهای واقعی می‌شد، چون
    اکثر رزومه‌ها این فناوری‌ها را با نقطه/پلاس/هش می‌نویسند: Node.js، C++،
    C#، ASP.NET، Vue.js و ...).

    راه‌حل: پیش از to_tsvector، نویسه‌های پرکاربرد در نام فناوری‌ها
    (./+#@_-) با translate() به فاصله تبدیل می‌شوند — یعنی "Node.js" عملاً
    مثل "Node js" توکنایز می‌شود و هم با جستجوی "Node" هم "js" هم "Node.js"
    (که حالا به AND دو کلمه تبدیل می‌شود) مطابقت پیدا می‌کند.
    """
    normalized = func.translate(
        func.coalesce(raw_text_column, literal_column("''")),
        literal_column(f"'{_FTS_PUNCTUATION_CHARS}'"),
        literal_column(f"'{_FTS_PUNCTUATION_REPLACEMENT}'"),
    )
    return func.to_tsvector("simple", normalized)
