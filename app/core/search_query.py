"""
تبدیل عبارت جستجوی متنی آزاد کاربر (با عملگرهای منطقی AND/OR، مثلاً "Python AND Django" یا "React OR Vue")
به شرط جستجو روی ایندکس کور رزومه‌ها (app/routers/candidates.py، موتور جستجوی پیشرفته‌ی رزومه‌ها).

حریم خصوصی: متن رزومه (resumes.raw_text) در دیتابیس رمزشده است و جستجوی تمام‌متن پستگرس (to_tsvector) روی آن
ممکن نیست. به‌جایش هر کلمه‌ی متن با HMAC و کلید محرمانه هش و در resumes.search_tokens (text[] با ایندکس GIN)
نگه داشته می‌شود (app/core/crypto.py). عبارت جستجو با همین نرمال‌سازی به کلمه شکسته، هش و با عملگر @> مقایسه
می‌شود — پس همان معنای AND/OR قبلی حفظ می‌شود (تطبیق کلمه‌ی کامل، بدون حساسیت به حروف بزرگ/کوچک).

چرا پارسر دستی؟ websearch_to_tsquery پستگرس «and» را عملگر نمی‌شناسد؛ این پارسر هر دو را صریح و
Case-Insensitive تشخیص می‌دهد و همین رفتار با ایندکس کور هم حفظ شده است.
"""

from __future__ import annotations

import re

from sqlalchemy import Float, Text, and_, func, or_
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.sql.elements import ColumnElement

# جداکننده‌ی عملگرهای منطقی: با فاصله از دو طرف احاطه شده باشند تا کلماتی
# مثل "Andrew" یا "Orlando" به اشتباه عملگر تشخیص داده نشوند.
_OPERATOR_SPLIT_PATTERN = re.compile(r"\s+(AND|OR)\s+", re.IGNORECASE)

# هر کلمه فقط از حروف (فارسی/انگلیسی) و اعداد تشکیل می‌شود؛ هر نویسه‌ی دیگر (، ؛ ' " و ...) حذف می‌شود.
_WORD_PATTERN = re.compile(r"\w+", re.UNICODE)

# نویسه‌های پرکاربرد در نام فناوری‌ها که کلمه را می‌شکنند: «Node.js» → node و js، «C++» → c، «C#» → c.
# پس جستجوی «Node» هم رزومه‌ای را که فقط «Node.js» نوشته پیدا می‌کند (رفتار قبلی جستجوی تمام‌متن حفظ شده).
_SPLIT_CHARS = str.maketrans({char: " " for char in "./+#@_-"})


def resume_search_words(text: str | None) -> list[str]:
    """
    نرمال‌سازی مشترک «متن رزومه هنگام ساخت ایندکس» و «عبارت جستجو» — این دو باید همیشه یکی باشند.
    خروجی: کلمات حروف‌کوچک به ترتیب ظهور (ممکن است تکراری باشند).
    """
    if not text:
        return []
    return [word.lower() for word in _WORD_PATTERN.findall(text.translate(_SPLIT_CHARS))]


def parse_search_query(raw_query: str | None) -> list[tuple[str, list[str]]]:
    """
    ورودی: عبارت خام جستجوی کاربر (پارامتر q).
    خروجی: [(عملگرِ اتصال به عبارت قبلی «&» یا «|»، کلمات عبارت), ...] — فهرست خالی اگر کلمه‌ی معتبری نماند.

    قوانین:
    - AND/OR به‌صورت Case-Insensitive شناسایی می‌شوند.
    - بین دو عبارت متوالیِ بدون عملگر صریح (فقط با فاصله جدا شده)، AND پیش‌فرض است؛ کلمات یک عبارت هم با
      هم AND می‌شوند.
    - عبارت‌ها از چپ به راست و بدون اولویت ضمنی بین AND/OR ترکیب می‌شوند تا رفتار قابل‌پیش‌بینی بماند.
    """
    if not raw_query or not raw_query.strip():
        return []

    terms: list[tuple[str, list[str]]] = []
    pending_operator = "&"
    for index, segment in enumerate(_OPERATOR_SPLIT_PATTERN.split(raw_query.strip())):
        # segments همیشه به‌صورت متناوب [عبارت, عملگر, عبارت, عملگر, ...] است
        if index % 2 == 1:
            pending_operator = "|" if segment.upper() == "OR" else "&"
            continue
        words = resume_search_words(segment)
        if words:
            terms.append((pending_operator, words))
    return terms


def resume_blind_index_condition(raw_query: str | None, search_tokens_column: ColumnElement) -> ColumnElement | None:
    """
    شرط SQL جستجوی متن رزومه روی ایندکس کور:  search_tokens @> ARRAY[hmac(word1), hmac(word2), ...]
    (هر عبارت = همه‌ی کلماتش)، ترکیب‌شده با AND/OR از چپ به راست. پستگرس هر @> را از ایندکس GIN
    ix_resumes_search_tokens_gin جواب می‌دهد. None اگر عبارت کلمه‌ی معتبری نداشته باشد.
    """
    from app.core.crypto import blind_index_token

    combined: ColumnElement | None = None
    for operator, words in parse_search_query(raw_query):
        hashed = sorted({blind_index_token(word) for word in words})
        # لیست با همان نوع ستون (text[]) Bind می‌شود؛ ARRAY[...] پارامترها را varchar[] می‌فرستاد و @> خطا می‌داد
        term = search_tokens_column.contains(hashed)
        if combined is None:
            combined = term
        else:
            combined = or_(combined, term) if operator == "|" else and_(combined, term)
    return combined


def resume_has_skill_condition(skill_analysis_column: ColumnElement, skill_name: str) -> ColumnElement:
    """
    شرط «این رزومه مهارت X را دارد» (بدون حساسیت به حروف بزرگ/کوچک) به شکلی که پستگرس از ایندکس GIN
    ix_resumes_skill_keys_gin استفاده کند (مایگریشن 9c4e2a7b1d35):

        ats_resume_skill_keys(skill_analysis) @> ARRAY[lower(:skill)]

    عبارت سمت چپ باید دقیقاً همان عبارت ایندکس باشد. نسخه‌ی قبلی (jsonb_array_elements_text + lower
    روی هر عنصر) هیچ ایندکسی را به کار نمی‌گرفت و با هر جستجو کل جدول resumes خوانده می‌شد.
    """
    skill_keys = func.ats_resume_skill_keys(skill_analysis_column, type_=ARRAY(Text))
    return skill_keys.contains(array([func.lower(skill_name)], type_=Text))


def resume_experience_years_expression(skill_analysis_column: ColumnElement) -> ColumnElement:
    """سابقه‌ی خالص (سال) طبق موتور مهارت — همان عبارت ایندکس ix_resumes_experience_years."""
    return func.ats_resume_experience_years(skill_analysis_column, type_=Float)
