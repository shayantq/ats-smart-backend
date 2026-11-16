"""تست رفت‌وبرگشت migration فاز ۶ فقط روی دیتابیس موقت و خالی از دادهٔ واقعی."""

import asyncpg
from sqlalchemy.engine import make_url

from tests.integration.test_tenancy_migration import legacy_database  # noqa: F401
from tests.integration.test_privacy_migration import _alembic


async def test_dossier_migration_round_trip_on_disposable_database(legacy_database):  # noqa: F811
    url = legacy_database.render_as_string(hide_password=False)
    names = ["dossier_review_heads", "dossier_review_events", "dossier_analysis_versions", "dossier_reanalysis_batches"]
    for action, target, present in [
        ("upgrade", "head", True),
        ("downgrade", "f19b3a47d682", False),
        ("upgrade", "head", True),
    ]:
        code, output = await _alembic(url, action, target)
        assert code == 0, output[-1500:]
        connection = await asyncpg.connect(
            make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            for name in names:
                assert bool(await connection.fetchval("SELECT to_regclass($1)", name)) == present
        finally:
            await connection.close()
