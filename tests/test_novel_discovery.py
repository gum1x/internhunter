from __future__ import annotations

import json
from typing import Any

import httpx
import numpy as np

from internhunter.discovery.similar import company_text, rank_neighbors
from internhunter.discovery.wayback import _cdx_url, _host, discover_from_wayback


# --- A3 Wayback ---
def test_host_from_pattern() -> None:
    assert _host("boards.greenhouse.io/*") == "boards.greenhouse.io"
    assert _host("*.recruitee.com/*") == "recruitee.com"


async def test_discover_from_wayback_parses_cdx(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    # canned CDX JSON: header row + two greenhouse board captures
    payload = [
        ["original"],
        ["https://boards.greenhouse.io/acmecorp/jobs/1"],
        ["https://boards.greenhouse.io/betacorp"],
    ]
    # only stub the greenhouse host's first page; others 404 -> fail soft
    ctx.responses[_cdx_url("boards.greenhouse.io", 1000, 0)] = httpx.Response(
        200, text=json.dumps(payload)
    )
    dets = await discover_from_wayback(ctx, ats=["greenhouse"])
    keys = {(d.ats, d.token) for d in dets}
    assert ("greenhouse", "acmecorp") in keys
    assert ("greenhouse", "betacorp") in keys


# --- A2 similar-company (pure ranking) ---
def test_company_text_uses_blurb() -> None:
    assert company_text({"name": "Acme", "long_description": "We build rockets."}) == (
        "Acme. We build rockets."
    )


def test_rank_neighbors_orders_by_similarity() -> None:
    # 3 vectors: seed at index 0; candidate 1 is identical to seed, candidate 2 orthogonal
    vectors = np.array(
        [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32
    )
    picks = rank_neighbors(vectors, seed_idx=[0], candidate_idx=[1, 2], max_total=2)
    assert picks[0] == 1  # most similar candidate first
    assert set(picks) == {1, 2}


def test_rank_neighbors_empty_when_no_seed() -> None:
    vectors = np.array([[1.0, 0.0]], dtype=np.float32)
    assert rank_neighbors(vectors, seed_idx=[], candidate_idx=[0], max_total=5) == []
