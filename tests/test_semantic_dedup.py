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


class ChainEncoder:
    """Maps three known job texts onto a chain: A~B and B~C but A is far from C.
    Vectors are chosen so that cos(A,B)=cos(B,C)>=0.9 and cos(A,C)<0.9."""

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        import math

        # Angles 0deg, ~22deg, ~44deg: adjacent pairs ~0.927 (>=0.9), A..C ~0.719 (<0.9).
        angle = {"A": 0.0, "B": math.radians(22.0), "C": math.radians(44.0)}
        rows: list[NDArray[np.float32]] = []
        for t in texts:
            key = next((k for k in angle if t.startswith(k)), "A")
            rows.append(
                np.array([math.cos(angle[key]), math.sin(angle[key])], dtype=np.float32)
            )
        return np.asarray(rows, dtype=np.float32)


def test_chain_clustering_is_order_independent() -> None:
    # A~B~C with A not similar to C. Connected-components must give ONE deterministic
    # group regardless of input order (the old greedy single-link was order-dependent).
    def make(tag: str, url: str) -> NormalizedJob:
        return _job(ats="greenhouse", url=url, title=tag, description_text=tag)

    a = make("A", "g1")
    b = make("B", "g2")
    c = make("C", "g3")

    def signature(jobs: list[NormalizedJob]) -> list[frozenset[str]]:
        groups = semantic_groups(jobs, ChainEncoder(), threshold=0.9)
        return sorted((frozenset(j.canonical_url for j in g) for g in groups), key=sorted)

    assert signature([a, b, c]) == signature([c, b, a])
    assert signature([a, b, c]) == signature([b, a, c])
    # All three land in one connected component (A-B edge and B-C edge).
    assert signature([a, b, c]) == [frozenset({"g1", "g2", "g3"})]
