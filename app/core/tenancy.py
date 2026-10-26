"""
هسته‌ی چندمستاجری (Multi-Tenancy): هر سازمان (ردیف جدول companies) یک Tenant است و داده‌ی
عملیاتی‌اش (آگهی، درخواست، رزومه، مصاحبه، …) با ستون tenant_id از بقیه جدا می‌شود.

ایزوله‌سازی در دو لایه‌ی مستقل انجام می‌شود تا یک باگ در یکی، به نشت داده نرسد:

    ۱. لایه‌ی برنامه (ORM): هر SELECT/UPDATE/DELETE روی مدل‌های TenantMixin خودکار شرط
       tenant_id = <سازمان کاربر> می‌گیرد (رویداد do_orm_execute + with_loader_criteria)،
       و ردیف‌های جدید خودکار tenant_id سازمان را می‌گیرند (رویداد before_flush).

    ۲. لایه‌ی دیتابیس (Row-Level Security): در شروع هر تراکنشِ یک درخواست API، نقش دیتابیس به
       ats_app (بدون مجوز عبور از RLS) و متغیرهای app.tenant_id / app.user_id / app.scope تنظیم
       می‌شوند (SET LOCAL — فقط تا پایان همان تراکنش). پالیسی‌های RLS (مایگریشن d2f6b8a41c37)
       هر ردیفی را که به سازمان جاری تعلق ندارد، حتی برای کوئری خام SQL، نامرئی می‌کنند.

حالت‌های Context:

    system     کارهای پس‌زمینه (Worker، زمان‌بند، مایگریشن، اسکریپت‌ها). پیش‌فرض بیرون از درخواست HTTP.
               نقش اصلی اتصال (مالک جدول‌ها) حفظ می‌شود و RLS اعمال نمی‌شود؛ این کدها خودشان
               tenant_id را صریح از رکورد والد می‌خوانند.
    tenant     کارمند یک سازمان (Admin / HR_Manager / Interviewer) — فقط داده‌ی همان سازمان.
    candidate  کارجو — فقط داده‌ی خودش (درخواست‌ها، رزومه‌ها) و آگهی‌های عمومی.
    public     بدون توکن معتبر — فقط آگهی‌های عمومی.

Context از توکن JWT (Claim «tid») در TenantContextMiddleware استخراج می‌شود؛ get_current_user
همان را با سازمان واقعی کاربر در دیتابیس تطبیق می‌دهد (توکن قدیمی/دست‌کاری‌شده → 401).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from jose import JWTError
from sqlalchemy import event, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.config import settings
from app.core.security import decode_token
from app.models.base import SharedTenantMixin, TenantMixin

SCOPE_SYSTEM = "system"
SCOPE_TENANT = "tenant"
SCOPE_CANDIDATE = "candidate"
SCOPE_PUBLIC = "public"


@dataclass(frozen=True)
class TenantContext:
    scope: str
    tenant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None

    @property
    def is_system(self) -> bool:
        return self.scope == SCOPE_SYSTEM


SYSTEM_CONTEXT = TenantContext(SCOPE_SYSTEM)
PUBLIC_CONTEXT = TenantContext(SCOPE_PUBLIC)

_current_context: ContextVar[TenantContext] = ContextVar("tenant_context", default=SYSTEM_CONTEXT)


class TenantAccessError(RuntimeError):
    """تلاش برای نوشتن ردیفی با tenant_id سازمان دیگر — نشانه‌ی باگ برنامه، نه خطای کاربر."""


def get_tenant_context() -> TenantContext:
    return _current_context.get()


def current_tenant_id() -> uuid.UUID | None:
    return _current_context.get().tenant_id


@contextmanager
def use_tenant_context(context: TenantContext) -> Iterator[TenantContext]:
    token = _current_context.set(context)
    try:
        yield context
    finally:
        _current_context.reset(token)


def context_from_token(token: str | None) -> TenantContext:
    """
    Context درخواست از روی access_token. توکن نامعتبر/منقضی → public (همان‌جا 401 نمی‌دهیم؛
    مسیرهای محافظت‌شده را get_current_user رد می‌کند و مسیرهای عمومی باید کار کنند).
    """
    if not token:
        return PUBLIC_CONTEXT
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return PUBLIC_CONTEXT
        user_id = uuid.UUID(str(payload.get("sub")))
        tenant_claim = payload.get("tid")
        if tenant_claim:
            return TenantContext(SCOPE_TENANT, tenant_id=uuid.UUID(str(tenant_claim)), user_id=user_id)
    except (JWTError, ValueError, TypeError):
        return PUBLIC_CONTEXT
    # توکن بدون tid: کارجو. کارمندِ دارای توکن قدیمی هم اینجا می‌افتد، ولی get_current_user ردش می‌کند.
    return TenantContext(SCOPE_CANDIDATE, user_id=user_id)


class TenantContextMiddleware:
    """
    Middleware خالص ASGI: tenant_id را از هدر Authorization (توکن JWT امضاشده) استخراج و در
    ContextVar درخواست قرار می‌دهد. شناسه‌ی سازمان هیچ‌وقت از پارامتر/بدنه‌ی درخواست خوانده نمی‌شود.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = None
        for name, value in scope.get("headers", ()):
            if name == b"authorization":
                scheme, _, credentials = value.decode("latin-1").partition(" ")
                if scheme.lower() == "bearer":
                    token = credentials.strip()
                break
        with use_tenant_context(context_from_token(token)):
            await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# لایه‌ی دیتابیس: نقش و متغیرهای RLS در شروع هر تراکنش
# ---------------------------------------------------------------------------
_APPLY_CONTEXT_SQL = text(
    "SELECT set_config('role', :role, true), set_config('app.scope', :scope, true), "
    "set_config('app.tenant_id', :tenant_id, true), set_config('app.user_id', :user_id, true)"
)


def _context_parameters(context: TenantContext) -> dict[str, str]:
    return {
        # «none» = بازگشت به نقش اصلی اتصال (معادل SET LOCAL ROLE NONE)
        "role": "none" if context.is_system else settings.DB_RLS_ROLE,
        "scope": "" if context.is_system else context.scope,
        "tenant_id": str(context.tenant_id) if context.tenant_id else "",
        "user_id": str(context.user_id) if context.user_id else "",
    }


@event.listens_for(Session, "after_begin")
def _apply_context_to_transaction(session, transaction, connection) -> None:
    if connection.dialect.name == "postgresql":  # RLS فقط در PostgreSQL (تست‌های واحد SQLite)
        connection.execute(_APPLY_CONTEXT_SQL, _context_parameters(get_tenant_context()))


async def apply_current_context(db: AsyncSession) -> None:
    """
    اعمال دوباره‌ی Context جاری روی تراکنشی که از قبل باز است (after_begin فقط در شروع تراکنش اجرا
    می‌شود). در برنامه هر درخواست Session خودش را دارد؛ این تابع برای Session مشترک بین چند درخواست
    (زیرساخت تست) و تغییر Context وسط تراکنش لازم است.
    """
    if db.in_transaction() and db.get_bind().dialect.name == "postgresql":
        await db.execute(_APPLY_CONTEXT_SQL, _context_parameters(get_tenant_context()))


@asynccontextmanager
async def system_scope(db: AsyncSession) -> AsyncIterator[None]:
    """
    اجرای یک بخش محدود و صریح از کد یک درخواست در حالت system — فقط برای کارهای سطح پلتفرم
    (مثلاً ساخت سازمان جدید هنگام ثبت‌نام). اگر تراکنش از قبل باز باشد، نقش و متغیرها همان لحظه
    عوض می‌شوند و در پایان به Context قبلی برمی‌گردند.
    """
    previous = get_tenant_context()
    with use_tenant_context(SYSTEM_CONTEXT):
        await apply_current_context(db)
        try:
            yield
        finally:
            with use_tenant_context(previous):
                await apply_current_context(db)


# ---------------------------------------------------------------------------
# لایه‌ی برنامه: فیلتر خودکار ORM و پر کردن خودکار tenant_id
# ---------------------------------------------------------------------------
@event.listens_for(Session, "do_orm_execute")
def _add_tenant_criteria(execute_state) -> None:
    context = get_tenant_context()
    if context.scope != SCOPE_TENANT or execute_state.is_column_load:
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    tenant_id = context.tenant_id
    options = [with_loader_criteria(TenantMixin, lambda cls: cls.tenant_id == tenant_id, include_aliases=True)]
    if execute_state.is_select:
        # مهارت‌های استاندارد (tenant_id خالی) برای همه خواندنی‌اند؛ مهارت سفارشی فقط برای سازمان خودش
        options.append(
            with_loader_criteria(
                SharedTenantMixin,
                lambda cls: or_(cls.tenant_id == tenant_id, cls.tenant_id.is_(None)),
                include_aliases=True,
            )
        )
    else:
        options.append(
            with_loader_criteria(SharedTenantMixin, lambda cls: cls.tenant_id == tenant_id, include_aliases=True)
        )
    execute_state.statement = execute_state.statement.options(*options)


@event.listens_for(Session, "before_flush")
def _stamp_tenant_on_new_rows(session, flush_context, instances) -> None:
    context = get_tenant_context()
    if context.scope != SCOPE_TENANT:
        return
    for instance in session.new:
        if not isinstance(instance, (TenantMixin, SharedTenantMixin)):
            continue
        if instance.tenant_id is None:
            instance.tenant_id = context.tenant_id
        elif instance.tenant_id != context.tenant_id:
            raise TenantAccessError(
                f"{type(instance).__name__}: tenant_id={instance.tenant_id} "
                f"با سازمان جاری ({context.tenant_id}) یکی نیست"
            )
