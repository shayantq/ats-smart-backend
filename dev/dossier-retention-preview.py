"""فقط برآورد نگه‌داری؛ هیچ DELETE اجرا نمی‌کند و سیاست خودکار فعال نمی‌شود."""

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from app.db.session import worker_session_factory
from app.models import DossierAnalysisVersion


async def preview(days, keep):
    ranked = select(
        DossierAnalysisVersion.id,
        DossierAnalysisVersion.created_at,
        func.row_number()
        .over(
            partition_by=DossierAnalysisVersion.application_id,
            order_by=(DossierAnalysisVersion.created_at.desc(), DossierAnalysisVersion.id),
        )
        .label("position"),
    ).subquery()
    async with worker_session_factory() as factory:
        async with factory() as db:
            count = (
                await db.execute(
                    select(func.count())
                    .select_from(ranked)
                    .where(
                        ranked.c.created_at < datetime.now(timezone.utc) - timedelta(days=days),
                        ranked.c.position > keep,
                    )
                )
            ).scalar_one()
    return dict(
        dry_run=True,
        delete_implemented=False,
        older_than_days=days,
        keep_latest_per_application=keep,
        eligible_snapshots=count,
        policy_approved=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--older-than-days", type=int, required=True)
    parser.add_argument("--keep-latest", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.older_than_days <= 3650 or not 1 <= args.keep_latest <= 50:
        parser.error("invalid_retention_bounds")
    print(json.dumps(asyncio.run(preview(args.older_than_days, args.keep_latest))))
