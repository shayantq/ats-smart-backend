"""
پیکربندی محیط اجرای Alembic.
چون پروژه از موتور async (asyncpg) استفاده می‌کند، این فایل با الگوی
async-compatible نوشته شده تا migration ها بتوانند بدون خطا اجرا شوند.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# --- اتصال به تنظیمات و مدل‌های پروژه ---
from app.core.config import settings
from app.models import Base  # noqa: F401  -> با import شدن، تمام ۱۴ مدل ثبت می‌شوند

# آبجکت Config المبیک که به مقادیر داخل alembic.ini دسترسی می‌دهد
config = context.config

# آدرس دیتابیس را از .env (نه از alembic.ini) می‌خوانیم تا هیچ پسوردی هاردکد نشود
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# تنظیم لاگ‌ها طبق فایل alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# متادیتای هدف برای autogenerate -> شامل تمام جداول تعریف‌شده در app/models
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """اجرای مایگریشن بدون اتصال مستقیم به دیتابیس (فقط تولید اسکریپت SQL)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """اجرای مایگریشن با اتصال واقعی async به دیتابیس PostgreSQL."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
