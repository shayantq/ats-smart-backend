"""
تست end-to-end خط لوله‌ی دیتاست آموزش تکمیلی روی PostgreSQL واقعی (داده‌ی ساختگی seeder):
seed ← build_dataset (استخراج جریانی + پاک‌سازی + ناشناس‌سازی + تقسیم) ← validate_dataset.
"""

import os

import pytest
from sqlalchemy import select, text

from app.datasets.finetune.build import BuildOptions, InsufficientPairsError, build_dataset
from app.datasets.finetune.cleanse import CleansingConfig
from app.datasets.finetune.extract import count_eligible_pairs, iter_pair_sources, readonly_session
from app.datasets.finetune.seed import ProductionRefusedError, ensure_not_production, seed
from app.datasets.finetune.tokenization import load_tokenizer
from app.datasets.finetune.validate import validate_dataset
from app.models import Application, Candidate, User
from tests.finetune_helpers import build_test_tokenizer

PAIRS = 120
SPLIT_FILES = ("train", "validation", "test")


@pytest.fixture
def tokenizer_path(tmp_path) -> str:
    return build_test_tokenizer(tmp_path)


async def _seeded(db_session) -> int:
    return await seed(pairs=PAIRS, tenants=2, seed_value=11, db=db_session)


def _options(out_dir, tokenizer_path, min_pairs: int = 10) -> BuildOptions:
    return BuildOptions(out_dir, tokenizer_path, min_pairs=min_pairs, cleansing=CleansingConfig(max_tokens=100_000))


async def test_end_to_end_build_produces_valid_anonymized_dataset(db_session, tmp_path, tokenizer_path):
    created = await _seeded(db_session)
    out_dir = tmp_path / "dataset"
    stats = await build_dataset(db_session, _options(out_dir, tokenizer_path))

    assert created >= PAIRS
    assert stats["eligible_pairs"] == stats["fetched_pairs"] <= created
    assert stats["kept"] == sum(split["records"] for split in stats["splits"].values()) > 0
    assert stats["kept"] + sum(stats["dropped"].values()) == stats["fetched_pairs"]
    assert sorted(path.name for path in out_dir.iterdir()) == sorted(
        ["manifest.json", "stats.json", *(f"{name}.jsonl" for name in SPLIT_FILES)]
    )
    if os.name != "nt":
        assert all(oct(path.stat().st_mode)[-3:] == "600" for path in out_dir.iterdir())

    report = validate_dataset(out_dir, load_tokenizer(tokenizer_path), 100_000, 0.2)
    assert report["status"] == "pass", report["issues"]


async def test_dataset_contains_no_seeded_identity(db_session, tmp_path, tokenizer_path):
    await _seeded(db_session)
    out_dir = tmp_path / "dataset"
    await build_dataset(db_session, _options(out_dir, tokenizer_path))
    content = "".join((out_dir / f"{name}.jsonl").read_text(encoding="utf-8") for name in SPLIT_FILES)
    query = select(Candidate.first_name, Candidate.last_name, Candidate.phone, User.email).join(
        User, User.id == Candidate.user_id
    )
    rows = (await db_session.execute(query)).all()
    assert rows
    for first, last, phone, email in rows:
        assert email not in content and phone not in content and phone[1:] not in content
        assert f"{first} {last}" not in content
    for leaked in ("@example.com", "linkedin.com", "seed/"):
        assert leaked not in content
    manifest = (out_dir / "manifest.json").read_text(encoding="utf-8")
    assert all(first not in manifest and email not in manifest for first, _, _, email in rows)


async def test_only_consented_candidates_are_eligible(db_session):
    await _seeded(db_session)
    before = await count_eligible_pairs(db_session)
    candidate_user = (
        await db_session.execute(
            select(User)
            .join(Candidate, Candidate.user_id == User.id)
            .join(Application, Application.candidate_id == Candidate.id)
            .where(User.data_consent_at.is_not(None))
            .limit(1)
        )
    ).scalar_one()
    applications = (
        (
            await db_session.execute(
                select(Application.id)
                .join(Candidate, Candidate.id == Application.candidate_id)
                .where(Candidate.user_id == candidate_user.id)
            )
        )
        .scalars()
        .all()
    )
    candidate_user.data_consent_at = None
    await db_session.commit()
    assert await count_eligible_pairs(db_session) == before - len(applications)


async def test_anonymized_accounts_are_excluded(db_session):
    await _seeded(db_session)
    before = await count_eligible_pairs(db_session)
    user = (
        await db_session.execute(
            select(User)
            .join(Candidate, Candidate.user_id == User.id)
            .join(Application, Application.candidate_id == Candidate.id)
            .where(User.data_consent_at.is_not(None))
            .limit(1)
        )
    ).scalar_one()
    user.anonymized_at = user.data_consent_at
    await db_session.commit()
    assert await count_eligible_pairs(db_session) < before


async def test_min_pairs_gate_stops_before_writing(db_session, tmp_path, tokenizer_path):
    await _seeded(db_session)
    out_dir = tmp_path / "dataset"
    with pytest.raises(InsufficientPairsError) as error:
        await build_dataset(db_session, _options(out_dir, tokenizer_path, min_pairs=10_000))
    assert error.value.required == 10_000 and error.value.eligible < 10_000
    assert not out_dir.exists()


async def test_resume_is_linked_to_application_by_score(db_session):
    await _seeded(db_session)
    sources = [source async for source in iter_pair_sources(db_session, batch_size=25)]
    linked = [source for source in sources if not source.ambiguous_link and source.score_ai is not None]
    assert linked
    for source in linked:
        assert round(source.analysis["matching"]["score"]) == source.score_ai


async def test_readonly_session_rejects_writes(test_database_url):
    async with readonly_session(test_database_url) as db:
        assert (await db.execute(text("SHOW transaction_read_only"))).scalar_one() == "on"
        assert await count_eligible_pairs(db) == 0
        with pytest.raises(Exception, match="read-only"):
            await db.execute(text("CREATE TABLE finetune_probe (id int)"))
        await db.rollback()  # تراکنش شکست‌خورده پیش از خروج از system_scope بسته می‌شود


def test_seeder_refuses_production():
    with pytest.raises(ProductionRefusedError):
        ensure_not_production("production")
    ensure_not_production("development")
