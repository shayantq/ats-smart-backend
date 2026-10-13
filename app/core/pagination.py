"""
صفحه‌بندی مبتنی بر نشانگر (Cursor / Keyset Pagination) — جایگزین صفحه‌بندی
سنتی Offset/Limit برای تمام اندپوینت‌های GET List پروژه.

چرا نه Offset/Limit؟
---------------------
با OFFSET N، پایگاه‌داده مجبور است N ردیف اول را واقعاً بخواند و دور بریزد؛
هرچه کاربر جلوتر برود (صفحه ۵۰۰ در برابر صفحه ۱) کوئری به‌طور خطی کندتر
می‌شود (O(N))؛ روی جدول‌هایی مثل applications یا resumes که قرار است حجم‌شان
به‌شدت رشد کند، همین رفتار دقیقاً همان «افت عملکرد» است که این تسک قرار است
جلویش را بگیرد.

Keyset Pagination با فیلتر `WHERE (sort_col, id) < (:cursor_val, :cursor_id)`
روی یک ایندکس B-Tree مرکب (بنگرید مایگریشن مربوطه) اجرا می‌شود؛ صرف‌نظر از
اینکه کاربر در صفحه‌ی ۱ باشد یا صفحه‌ی ۵۰۰، دیتابیس مستقیم به نقطه‌ی درست
می‌پرد (O(log N)).

هر cursor یک توکن مات (Opaque, Base64) است که موضع دقیق آخرین/اولین رکورد
صفحه‌ی فعلی را رمزنگاری می‌کند: (مقدار ستون مرتب‌سازی، id رکورد). ترکیب این
دو مقدار (Composite Cursor) لازم است تا حتی اگر چند رکورد مقدار یکسانی در
ستون مرتب‌سازی داشته باشند (مثلاً چند درخواست با updated_at دقیقاً یکسان)،
صفحه‌بندی همچنان صحیح بماند و هیچ رکوردی گم یا تکراری نشود.

نکته‌ی عمدی درباره‌ی «total»: بر خلاف الگوی قدیمی (`{"total": ..., "items": [...]}`)،
این پاسخ‌ها دیگر total برنمی‌گردانند؛ محاسبه‌ی COUNT(*) دقیق روی جدول‌های
حجیم دقیقاً همان نوع کوئری کندی است که این تسک قرار است حذفش کند. به‌جایش
has_next/has_previous (که با یک کوئری سبک LIMIT 1 روی همان ایندکس محاسبه
می‌شوند) کفایت می‌کند.
"""

from __future__ import annotations

import base64
import json
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar

from fastapi import HTTPException, Query, status
from sqlalchemy import Select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

T = TypeVar("T")

_INVALID_CURSOR_DETAIL = "توکن صفحه‌بندی (cursor) نامعتبر یا دستکاری‌شده است."


class InvalidCursorError(ValueError):
    """وقتی توکن cursor ارسالی توسط کلاینت قابل رمزگشایی/معتبر نباشد."""


@dataclass(frozen=True)
class CursorParams:
    """پارامترهای صفحه‌بندی که از Query String خوانده می‌شوند."""

    cursor: str | None
    direction: str
    limit: int


def cursor_params(
    cursor: str | None = Query(
        default=None,
        description="توکن صفحه‌ای که می‌خواهید بخوانید (از فیلد next_cursor/previous_cursor پاسخ قبلی). "
        "خالی = اولین صفحه.",
    ),
    direction: str = Query(
        default="next",
        pattern="^(next|prev)$",
        description="جهت حرکت نسبت به cursor: 'next' (صفحه‌ی بعد) یا 'prev' (صفحه‌ی قبل).",
    ),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"تعداد آیتم در هر صفحه (حداکثر {MAX_PAGE_SIZE}).",
    ),
) -> CursorParams:
    """Dependency مشترک برای خواندن cursor/direction/limit در تمام مسیرهای GET List."""
    return CursorParams(cursor=cursor, direction=direction, limit=limit)


@dataclass(frozen=True)
class CursorPage(Generic[T]):
    items: list[T]
    next_cursor: str | None
    previous_cursor: str | None
    has_next: bool
    has_previous: bool


def _serialize_sort_value(value: Any) -> tuple[str, Any]:
    if isinstance(value, datetime):
        return "dt", value.isoformat()
    if isinstance(value, bool):
        return "str", str(value)
    if isinstance(value, int):
        return "int", value
    return "str", str(value)


def _deserialize_sort_value(kind: str, raw: Any) -> Any:
    if kind == "dt":
        return datetime.fromisoformat(raw)
    if kind == "int":
        return int(raw)
    return raw


def _deserialize_id_value(raw: str) -> Any:
    """اگر id به فرمت UUID باشد به uuid.UUID تبدیل می‌شود؛ در غیر این صورت رشته باقی می‌ماند."""
    try:
        return uuid_module.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return raw


def encode_cursor(sort_value: Any, row_id: Any) -> str:
    """موضع یک رکورد (مقدار ستون مرتب‌سازی + id) را به یک توکن مات Base64 تبدیل می‌کند."""
    kind, serialized_value = _serialize_sort_value(sort_value)
    payload = {"v": serialized_value, "k": kind, "id": str(row_id)}
    raw_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii")


def decode_cursor(cursor: str) -> tuple[Any, Any]:
    """توکن cursor را به (مقدار ستون مرتب‌سازی، id) رمزگشایی می‌کند."""
    try:
        raw_bytes = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw_bytes)
        sort_value = _deserialize_sort_value(payload["k"], payload["v"])
        row_id = _deserialize_id_value(payload["id"])
        return sort_value, row_id
    except Exception as exc:  # noqa: BLE001 - هر خطایی یعنی توکن دستکاری/خراب شده
        raise InvalidCursorError(_INVALID_CURSOR_DETAIL) from exc


def _unwrap_row(row: Any) -> Any:
    """
    نتیجه‌ی result.all() برای select(Model) یک Row تک‌ستونه (شامل خودِ Entity)
    برمی‌گرداند و برای select(col1, col2, ...) یک Row چندستونه با دسترسی
    مستقیم به هر ستون (row.col_name). این تابع حالت اول را باز می‌کند تا
    caller مستقیماً همان Entity (مثلاً Job) را در دست داشته باشد، دقیقاً
    مثل نتیجه‌ی result.scalars().all()؛ حالت دوم را دست‌نخورده برمی‌گرداند.
    """
    if len(row) == 1:
        return row[0]
    return row


def _extract(item: Any, column: InstrumentedAttribute) -> Any:
    """مقدار یک ستون را چه از یک Entity (Job) چه از یک Row چندستونه بخواند."""
    key = column.key
    mapping = getattr(item, "_mapping", None)
    if mapping is not None:
        return mapping[key]
    return getattr(item, key)


async def paginate_by_cursor(
    db: AsyncSession,
    query: Select,
    *,
    sort_column: InstrumentedAttribute,
    id_column: InstrumentedAttribute,
    params: CursorParams,
    descending: bool = True,
) -> CursorPage:
    """
    یک صفحه از نتایج `query` را با روش Keyset (Cursor) Pagination برمی‌گرداند.

    ورودی `query` باید فقط شامل SELECT/JOIN/WHERE (فیلترهای کسب‌وکاری مسیر،
    مثل job_id=... یا candidate_id=...) باشد — بدون order_by/limit/offset؛
    این تابع خودش مرتب‌سازی و محدودسازی را روی همان query اضافه می‌کند.

    sort_column: ستون اصلی مرتب‌سازی (مثلاً Application.updated_at).
    id_column:   ستون کلید یکتا برای شکستن تساوی (Tie-Breaker)، معمولاً همان
                 primary key جدول (مثلاً Application.id) — چون sort_column
                 به‌تنهایی ممکن است در چند رکورد مقدار یکسان داشته باشد.
    descending:  ترتیب نمایش پیش‌فرض؛ True یعنی جدیدترین اول (مثل بورد کانبان)،
                 False یعنی قدیمی‌ترین اول (مثل لیست زمان‌بندی‌شده‌ی مصاحبه‌ها).
    """
    limit = params.limit
    direction = params.direction

    cursor_value: Any = None
    cursor_id: Any = None
    if params.cursor is not None:
        try:
            cursor_value, cursor_id = decode_cursor(params.cursor)
        except InvalidCursorError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # جهت واقعی fetch: برای next همان جهت نمایش، برای prev برعکسِ جهت نمایش
    # (تا نزدیک‌ترین رکوردهای قبل از cursor خوانده شوند، سپس دوباره reverse می‌شوند)
    fetch_descending = descending if direction == "next" else not descending

    fetch_query = query
    if params.cursor is not None:
        boundary = (cursor_value, cursor_id)
        if fetch_descending:
            fetch_query = fetch_query.where(tuple_(sort_column, id_column) < boundary)
        else:
            fetch_query = fetch_query.where(tuple_(sort_column, id_column) > boundary)

    order_by_cols = (sort_column.desc(), id_column.desc()) if fetch_descending else (sort_column.asc(), id_column.asc())
    # یک ردیف بیشتر از limit خوانده می‌شود: وجودش یعنی در «جهت fetch» صفحه‌ی دیگری هست — بدون کوئری جدا
    fetch_query = fetch_query.order_by(*order_by_cols).limit(limit + 1)

    result = await db.execute(fetch_query)
    items = [_unwrap_row(row) for row in result.all()]
    has_more_in_fetch_direction = len(items) > limit
    items = items[:limit]

    if direction == "prev":
        items.reverse()  # برگرداندن به همان ترتیب نمایش عادی (descending/ascending اصلی)

    if not items:
        return CursorPage(items=[], next_cursor=None, previous_cursor=None, has_next=False, has_previous=False)

    first_item = items[0]
    last_item = items[-1]
    next_boundary = (_extract(last_item, sort_column), _extract(last_item, id_column))
    prev_boundary = (_extract(first_item, sort_column), _extract(first_item, id_column))

    async def exists_beyond(boundary: tuple, after: bool) -> bool:
        """آیا رکوردی بعد (after=True) یا قبل از boundary (در ترتیب نمایش) وجود دارد؟"""
        go_lower = descending if after else not descending
        condition = tuple_(sort_column, id_column) < boundary if go_lower else tuple_(sort_column, id_column) > boundary
        return (await db.execute(query.where(condition).limit(1))).first() is not None

    # یافته‌ی تست بار: قبلاً هر صفحه ۳ کوئری داشت (صفحه + دو کوئری بررسی صفحه‌ی بعد/قبل). حالا
    # جهت fetch از همان ردیف اضافه معلوم است و «صفحه‌ی قبل» در اولین صفحه (بدون cursor) قطعاً وجود
    # ندارد — پس رایج‌ترین درخواست (صفحه‌ی اول) فقط ۱ کوئری می‌زند، با نتیجه‌ای دقیقاً یکسان.
    if direction == "next":
        has_next = has_more_in_fetch_direction
        has_previous = params.cursor is not None and await exists_beyond(prev_boundary, after=False)
    else:
        has_previous = has_more_in_fetch_direction
        has_next = await exists_beyond(next_boundary, after=True)

    next_cursor = encode_cursor(*next_boundary) if has_next else None
    previous_cursor = encode_cursor(*prev_boundary) if has_previous else None

    return CursorPage(
        items=items,
        next_cursor=next_cursor,
        previous_cursor=previous_cursor,
        has_next=has_next,
        has_previous=has_previous,
    )
