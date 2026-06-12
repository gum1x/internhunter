from __future__ import annotations

from datetime import datetime


def freshness_score(
    posted_at: datetime | None, now: datetime, half_life_days: float = 14.0
) -> float:
    if posted_at is None:
        return 0.3
    age_days = (now - posted_at).total_seconds() / 86400.0
    if age_days <= 0.0:
        return 1.0
    score = float(0.5 ** (age_days / half_life_days))
    return max(0.0, min(1.0, score))


def rarity_score(times_seen_elsewhere: int, board_total_jobs: int | None = None) -> float:
    seen = max(0, times_seen_elsewhere)
    spread = 1.0 / (1.0 + seen)
    if board_total_jobs is None:
        return max(0.0, min(1.0, spread))
    size = max(0, board_total_jobs)
    smallness = 1.0 / (1.0 + size / 50.0)
    score = 0.5 * spread + 0.5 * smallness
    return max(0.0, min(1.0, score))


def discovery_score(
    fit: float,
    freshness: float,
    rarity: float,
    w_fit: float = 0.5,
    w_fresh: float = 0.25,
    w_rarity: float = 0.25,
) -> float:
    total = w_fit + w_fresh + w_rarity
    if total <= 0.0:
        return 0.0
    score = (w_fit * fit + w_fresh * freshness + w_rarity * rarity) / total
    return max(0.0, min(1.0, score))
