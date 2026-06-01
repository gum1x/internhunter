from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import numpy as np
from numpy.typing import NDArray

from internhunter.core.models import NormalizedJob
from internhunter.match.semantic_dedup import collapse_semantic, semantic_groups


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


def _job(
    *,
    ats: str,
    url: str,
    company_slug: str = "acme",
    title: str = "Software Engineering Intern",
    description_text: str = "Build great things.",
    posted_at: datetime | None = None,
    first_seen_at: datetime | None = None,
) -> NormalizedJob:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return NormalizedJob(
        job_uid=f"{ats}:{url}",
        ats=ats,
        board_token="acme",
        canonical_url=url,
        url_hash=url,
        company_slug=company_slug,
        title=title,
        title_normalized=title.lower(),
        description_text=description_text,
        posted_at=posted_at,
        first_seen_at=first_seen_at or now,
        last_seen_at=first_seen_at or now,
    )


def test_identical_same_company_collapses() -> None:
    a = _job(ats="bamboohr", url="b1")
    b = _job(ats="greenhouse", url="g1")

    canonicals, merged = collapse_semantic([a, b], FakeEncoder())

    assert len(canonicals) == 1
    assert merged == 1
    assert canonicals[0].ats == "greenhouse"
    assert canonicals[0].times_seen_elsewhere == 1


def test_different_text_stays_separate() -> None:
    a = _job(ats="greenhouse", url="g1", title="Software Engineering Intern")
    b = _job(
        ats="lever",
        url="l1",
        title="Marketing Coordinator",
        description_text="Run social campaigns and events.",
    )

    groups = semantic_groups([a, b], FakeEncoder(), threshold=0.9)

    assert len(groups) == 2


def test_different_company_identical_text_does_not_merge() -> None:
    a = _job(ats="greenhouse", url="g1", company_slug="acme")
    b = _job(ats="greenhouse", url="g2", company_slug="globex")

    canonicals, merged = collapse_semantic([a, b], FakeEncoder())

    assert len(canonicals) == 2
    assert merged == 0


def test_three_member_identical_group() -> None:
    a = _job(ats="greenhouse", url="g1")
    b = _job(ats="lever", url="l1")
    c = _job(ats="ashby", url="ab1")

    canonicals, merged = collapse_semantic([a, b, c], FakeEncoder())

    assert len(canonicals) == 1
    assert merged == 2
    assert canonicals[0].times_seen_elsewhere == 2
