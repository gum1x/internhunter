from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Job, get_session, init_db
from internhunter.core.fetch import FetchContext
from internhunter.core.normalize import normalize_company_slug
from internhunter.discovery.careers import resolve_many
from internhunter.discovery.fingerprint import Detection
from internhunter.discovery.yc import fetch_yc_companies
from internhunter.match.embed import EmbeddingCache, Encoder, cosine_matrix, embed_texts


def company_text(c: dict[str, Any]) -> str:
    name = str(c.get("name") or "")
    blurb = str(c.get("long_description") or c.get("one_liner") or "")
    return f"{name}. {blurb}".strip()


def rank_neighbors(
    vectors: NDArray[np.float32],
    seed_idx: list[int],
    candidate_idx: list[int],
    max_total: int,
) -> list[int]:
    """Candidate indices ranked by best cosine similarity to ANY seed company.

    Pure (no I/O) so it can be unit-tested with a fake embedding matrix.
    """
    if not seed_idx or not candidate_idx or vectors.size == 0:
        return []
    sims = cosine_matrix(vectors[seed_idx], vectors[candidate_idx])  # (seeds, candidates)
    best = sims.max(axis=0)
    order = list(np.argsort(best)[::-1])
    return [candidate_idx[int(j)] for j in order[:max_total]]


async def discover_similar_companies(
    ctx: FetchContext,
    settings: Settings | None = None,
    encoder: Encoder | None = None,
) -> list[Detection]:
    """Embed the companies we already win on, crawl their semantic neighbors in the YC
    universe (gated on isHiring). Targets the long tail by *relevance*, not brute breadth.
    Returns [] if sentence-transformers isn't installed or there are no seeds.
    """
    resolved = settings or get_settings()
    companies = await fetch_yc_companies(ctx)
    if not companies:
        return []
    slugs = [normalize_company_slug(c.get("name") or "") for c in companies]

    init_db(resolved.db_path)
    session = get_session()
    try:
        tracked = set(
            session.scalars(
                select(Job.company_slug).where(Job.is_internship.is_(True)).distinct()
            )
        )
    finally:
        session.close()

    seed_idx = [i for i, sl in enumerate(slugs) if sl and sl in tracked]
    if not seed_idx:
        return []
    seed_set = set(seed_idx)
    candidate_idx = [
        i
        for i, c in enumerate(companies)
        if i not in seed_set and c.get("isHiring") and slugs[i] not in tracked
    ]
    if not candidate_idx:
        return []

    if encoder is None:
        try:
            from internhunter.match.embed import default_encoder

            encoder = default_encoder(resolved.embed_model)
        except Exception:
            ctx.logger.debug("similar: no embedding encoder available")
            return []

    texts = [company_text(c) for c in companies]
    cache = EmbeddingCache(resolved.cache_dir, resolved.embed_model)
    vectors = embed_texts(texts, encoder, cache)

    picks = rank_neighbors(vectors, seed_idx, candidate_idx, resolved.similar_max_crawls)
    sites = [
        companies[i]["website"]
        for i in picks
        if isinstance(companies[i].get("website"), str)
    ]
    return await resolve_many(ctx, sites)
