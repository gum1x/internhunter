from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import numpy as np
from numpy.typing import NDArray

from internhunter.core.models import NormalizedJob
from internhunter.match.prefilter import job_text, load_profile_text, rank_jobs


class FakeEncoder:
    def __init__(self, dim: int = 32) -> None:
        self.dim = dim

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        rows: list[NDArray[np.float32]] = []
        for t in texts:
            seed = int(hashlib.sha1(t.encode()).hexdigest()[:8], 16)
            rows.append(
                np.random.default_rng(seed).standard_normal(self.dim).astype(np.float32)
            )
        return np.asarray(rows, dtype=np.float32)


def make_job(title: str, description: str) -> NormalizedJob:
    now = datetime.now(UTC)
    return NormalizedJob(
        job_uid=f"uid-{title}",
        ats="greenhouse",
        board_token="acme",
        canonical_url=f"https://example.com/{title}",
        url_hash=hashlib.sha1(title.encode()).hexdigest(),
        company_slug="acme",
        title=title,
        title_normalized=title.lower(),
        description_text=description,
        first_seen_at=now,
        last_seen_at=now,
    )


def test_rank_jobs_sorted_descending() -> None:
    match_job = make_job("python data engineer", "ml pipelines")
    profile = job_text(match_job)
    jobs = [
        match_job,
        make_job("warehouse forklift operator", "manual labor"),
        make_job("sales associate", "retail floor"),
    ]
    ranked = rank_jobs(profile, jobs, FakeEncoder())
    scores = [score for _, score in ranked]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_matching_job_ranks_above_unrelated() -> None:
    match_job = make_job("python data engineer", "ml pipelines")
    profile = job_text(match_job)
    other_job = make_job("warehouse forklift operator", "manual labor")
    ranked = rank_jobs(profile, [other_job, match_job], FakeEncoder())
    assert ranked[0][0].job_uid == match_job.job_uid
    assert ranked[0][1] > ranked[1][1]


def test_empty_jobs_returns_empty() -> None:
    assert rank_jobs("anything", [], FakeEncoder()) == []


def test_job_text() -> None:
    job = make_job("Backend Intern", "Build APIs in python.")
    assert job_text(job) == "Backend Intern. Build APIs in python."


def test_load_profile_text() -> None:
    text = load_profile_text()
    assert isinstance(text, str)
    assert text
    assert "python" in text.lower()
