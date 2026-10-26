"""
ساخت یک حساب Admin مخصوص اسکن امنیتی و چاپ یک access_token با عمر ۳ ساعت (به‌جای ۱۵ دقیقه‌ی
عادی — یک Active Scan کامل ممکن است بیش از ۱۵ دقیقه طول بکشد). فقط برای محیط تست:

    docker compose exec -T backend_api python - < security/zap_token.py
"""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.core.security import _create_token, hash_password
from app.core.tenant_provisioning import provision_tenant
from app.db.session import AsyncSessionLocal
from app.models import User

SCANNER_EMAIL = "zap-scanner@example.com"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == SCANNER_EMAIL))).scalar_one_or_none()
        if user is None:
            user = User(email=SCANNER_EMAIL, password_hash=hash_password("ZapScanner!2026"), role="Admin")
        if user.tenant_id is None:
            # چندمستاجری: Admin همیشه عضو یک سازمان است؛ اسکنر سازمان آزمایشی خودش را دارد
            await provision_tenant(db, name="Security Scan Org", owner=user)
            await db.commit()
        token, _ = _create_token(
            str(user.id), timedelta(hours=3), token_type="access", extra_claims={"tid": str(user.tenant_id)}
        )
        print(token)


asyncio.run(main())
