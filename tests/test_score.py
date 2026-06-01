from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings
from internhunter.core.db import Job, Score
from internhunter.match.score import _job_text, score_jobs


class FakeEncoder:
    def __init__(self, dim: int = 32) -> None:
        self.dim = dim

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        rows = []
        for text in texts:
            seed = int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)
            rows.append(np.random.default_rng(seed).standard_normal(self.dim))
        return np.asarray(rows, dtype=np.float32)


def _job(uid: str, title: str, desc: str) -> Job:
    now = datetime(2026, 6, 1)
    return Job(
        job_uid=uid,
        ats="greenhouse",
        board_token="acme",
        canonical_url=f"https://x/{uid}",
        url_hash=uid,
        company="Acme",
        company_slug="acme",
        title=title,
        title_normalized=title.lower(),
        description_text=desc,
        is_internship=True,
        first_seen_at=now,
        last_seen_at=now,
        posted_at=now,
    )


def test_score_jobs_persists_scores_and_ranks(db_session: Session, tmp_path: Path) -> None:
    match = _job("m1", "python machine learning internship", "")
    other = _job("o1", "warehouse forklift operator night shift", "")
    profile = _job_text(match)
    db_session.add_all([match, other])
    db_session.commit()

    settings = Settings(cache_dir=tmp_path / "cache", db_path=tmp_path / "t.db")
    count = score_jobs(
        db_session,
        FakeEncoder(),
        profile_text=profile,
        settings=settings,
        now=datetime(2026, 6, 1, tzinfo=UTC),
    )
    assert count == 2

    scored_match = db_session.scalar(select(Job).where(Job.job_uid == "m1"))
    scored_other = db_session.scalar(select(Job).where(Job.job_uid == "o1"))
    assert scored_match is not None and scored_other is not None
    assert scored_match.discovery_score is not None
    assert scored_match.freshness_score is not None
    assert scored_match.rarity_score is not None

    assert scored_match.discovery_score > scored_other.discovery_score

    score_row = db_session.scalar(select(Score).where(Score.job_uid == "m1"))
    assert score_row is not None
    assert score_row.fit_score is not None
    assert score_row.fit_score > 0.99


def test_score_jobs_empty_db(db_session: Session, tmp_path: Path) -> None:
    settings = Settings(cache_dir=tmp_path / "cache", db_path=tmp_path / "t.db")
    assert score_jobs(db_session, FakeEncoder(), profile_text="x", settings=settings) == 0
